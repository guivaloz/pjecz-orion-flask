"""
Incapacidades, vistas
"""

import json
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from lib.datatables import get_datatable_parameters, output_datatable_json
from lib.safe_string import safe_string, safe_message

from orion.blueprints.bitacoras.models import Bitacora
from orion.blueprints.modulos.models import Modulo
from orion.blueprints.permisos.models import Permiso
from orion.blueprints.usuarios.decorators import permission_required
from orion.blueprints.incapacidades.models import Incapacidad
from orion.blueprints.personas.models import Persona
from orion.blueprints.incapacidades.forms import IncapacidadForm, IncapacidadWithPersonaForm
from orion.blueprints.historial_puestos.models import HistorialPuesto

MODULO = "INCAPACIDADES"

incapacidades = Blueprint("incapacidades", __name__, template_folder="templates")


@incapacidades.before_request
@login_required
@permission_required(MODULO, Permiso.VER)
def before_request():
    """Permiso por defecto"""


@incapacidades.route("/incapacidades/datatable_json", methods=["GET", "POST"])
def datatable_json():
    """DataTable JSON para listado de Incapacidades"""
    # Tomar parámetros de Datatables
    draw, start, rows_per_page = get_datatable_parameters()
    # Consultar
    consulta = Incapacidad.query
    # Primero filtrar por columnas propias
    if "estatus" in request.form:
        consulta = consulta.filter(Incapacidad.estatus == request.form["estatus"])
    else:
        consulta = consulta.filter(Incapacidad.estatus == "A")
    if "fecha_inicio" in request.form:
        consulta = consulta.filter(Incapacidad.fecha_inicio >= request.form["fecha_inicio"])
    if "fecha_termino" in request.form:
        consulta = consulta.filter(Incapacidad.fecha_termino <= request.form["fecha_termino"])
    # Luego filtrar por columnas de otras tablas
    if "persona_nombre_completo" in request.form:
        nombre_completo = safe_string(request.form["persona_nombre_completo"])
        if nombre_completo != "":
            consulta = consulta.join(Persona)
            for palabra in nombre_completo.split(" "):
                consulta = consulta.filter(
                    or_(
                        Persona.nombres.contains(palabra),
                        Persona.apellido_primero.contains(palabra),
                        Persona.apellido_segundo.contains(palabra),
                    )
                )
    if "persona_id" in request.form:
        consulta = consulta.join(Persona)
        consulta = consulta.filter(Persona.id == request.form["persona_id"])
    # Ordenar y paginar
    registros = consulta.order_by(Incapacidad.fecha_inicio.desc()).offset(start).limit(rows_per_page).all()
    total = consulta.count()
    # Elaborar datos para DataTable
    data = []
    for resultado in registros:
        data.append(
            {
                "detalle": {
                    "periodo": resultado.fecha_inicio.strftime("%Y-%m-%d")
                    + " — "
                    + resultado.fecha_termino.strftime("%Y-%m-%d"),
                    "url": url_for("incapacidades.detail", incapacidad_id=resultado.id),
                },
                "persona": {
                    "nombre": resultado.persona.nombre_completo,
                    "url": url_for("personas.detail", persona_id=resultado.persona.id),
                },
                "dias": f"{(resultado.fecha_termino - resultado.fecha_inicio).days + 1} DÍAS",
                "motivo": resultado.motivo,
            }
        )
    # Entregar JSON
    return output_datatable_json(draw, total, data)


@incapacidades.route("/incapacidades")
def list_active():
    """Listado de Incapacidades activos"""
    return render_template(
        "incapacidades/list.jinja2",
        filtros=json.dumps({"estatus": "A"}),
        titulo="Incapacidades",
        estatus="A",
    )


@incapacidades.route("/incapacidades/inactivos")
@permission_required(MODULO, Permiso.ADMINISTRAR)
def list_inactive():
    """Listado de Incapacidades inactivos"""
    return render_template(
        "incapacidades/list.jinja2",
        filtros=json.dumps({"estatus": "B"}),
        titulo="Incapacidades inactivos",
        estatus="B",
    )


@incapacidades.route("/incapacidades/<int:incapacidad_id>")
def detail(incapacidad_id):
    """Detalle de una Incapacidad"""
    incapacidad = Incapacidad.query.get_or_404(incapacidad_id)
    return render_template("incapacidades/detail.jinja2", incapacidad=incapacidad)


@incapacidades.route("/incapacidades/nuevo", methods=["GET", "POST"])
@permission_required(MODULO, Permiso.CREAR)
def new():
    """Nuevo Incapacidad"""
    form = IncapacidadForm()
    if form.validate_on_submit():
        # Validar fecha
        if form.fecha_termino.data < form.fecha_inicio.data:
            flash("La fecha de inicio no puede ser mayor a la fecha de termino.", "warning")
            return render_template("incapacidades/new.jinja2", form=form)
        # Validar registro repetido
        registro_repetido = (
            Incapacidad.query.filter_by(persona_id=form.persona.data)
            .filter_by(fecha_inicio=form.fecha_inicio.data)
            .filter_by(fecha_termino=form.fecha_termino.data)
            .filter_by(estatus="A")
            .first()
        )
        if registro_repetido:
            flash("Esta persona ya tiene una incapacidad en la misma fecha de inicio y término.", "warning")
            return render_template("incapacidades/new.jinja2", form=form)
        # Buscar puesto en historial de puestos
        puesto_nombre = None
        historial_puesto = HistorialPuesto.query.filter_by(persona_id=form.persona.data).filter_by(estatus="A")
        historial_puesto = historial_puesto.filter(form.fecha_inicio.data >= HistorialPuesto.fecha_inicio)
        historial_puesto = historial_puesto.order_by(HistorialPuesto.fecha_inicio.desc()).first()
        if historial_puesto:
            puesto_nombre = historial_puesto.puesto_funcion.nombre
        # Guardar registro
        incapacidad = Incapacidad(
            persona_id=form.persona.data,
            fecha_inicio=form.fecha_inicio.data,
            fecha_termino=form.fecha_termino.data,
            clave_incapacidad=safe_string(form.clave_incapacidad.data),
            region=form.region.data,
            motivo=safe_string(form.motivo.data, save_enie=True),
            puesto_nombre=puesto_nombre,
        )
        incapacidad.save()
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=safe_message(f"Nuevo Incapacidad {incapacidad.persona.nombre_completo}"),
            url=url_for("incapacidades.detail", incapacidad_id=incapacidad.id),
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
        return redirect(bitacora.url)
    return render_template("incapacidades/new.jinja2", form=form)


@incapacidades.route("/incapacidades/nuevo_con_persona/<int:persona_id>", methods=["GET", "POST"])
@permission_required(MODULO, Permiso.CREAR)
def new_with_persona_id(persona_id):
    """Nuevo Incapacidad"""
    persona = Persona.query.get_or_404(persona_id)
    form = IncapacidadWithPersonaForm()
    if form.validate_on_submit():
        # Validar fecha
        if form.fecha_termino.data < form.fecha_inicio.data:
            flash("La fecha de inicio no puede ser mayor a la fecha de termino.", "warning")
            return render_template("incapacidades/new_with_persona_id.jinja2", form=form, persona=persona)
        # Validar registro repetido
        registro_repetido = (
            Incapacidad.query.filter_by(persona=persona)
            .filter_by(fecha_inicio=form.fecha_inicio.data)
            .filter_by(fecha_termino=form.fecha_termino.data)
            .filter_by(estatus="A")
            .first()
        )
        if registro_repetido:
            flash("Esta persona ya tiene una incapacidad en la misma fecha de inicio y término.", "warning")
            return render_template("incapacidades/new_with_persona_id.jinja2", form=form, persona=persona)
        # Buscar puesto en historial de puestos
        puesto_nombre = None
        historial_puesto = HistorialPuesto.query.filter_by(persona=persona).filter_by(estatus="A")
        historial_puesto = historial_puesto.filter(form.fecha_inicio.data >= HistorialPuesto.fecha_inicio)
        historial_puesto = historial_puesto.order_by(HistorialPuesto.fecha_inicio.desc()).first()
        if historial_puesto:
            puesto_nombre = historial_puesto.puesto_funcion.nombre
        # Guardar registro
        incapacidad = Incapacidad(
            persona=persona,
            fecha_inicio=form.fecha_inicio.data,
            fecha_termino=form.fecha_termino.data,
            clave_incapacidad=safe_string(form.clave_incapacidad.data),
            region=form.region.data,
            motivo=safe_string(form.motivo.data, save_enie=True),
            puesto_nombre=puesto_nombre,
        )
        incapacidad.save()
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=safe_message(f"Nuevo Incapacidad {incapacidad.persona.nombre_completo}"),
            url=url_for("incapacidades.detail", incapacidad_id=incapacidad.id),
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
        return redirect(bitacora.url)
    form.persona.data = persona.nombre_completo
    return render_template("incapacidades/new_with_persona_id.jinja2", form=form, persona=persona)


@incapacidades.route("/incapacidades/edicion/<int:incapacidad_id>", methods=["GET", "POST"])
@permission_required(MODULO, Permiso.MODIFICAR)
def edit(incapacidad_id):
    """Editar Incapacidad"""
    incapacidad = Incapacidad.query.get_or_404(incapacidad_id)
    form = IncapacidadWithPersonaForm()
    if form.validate_on_submit():
        es_valido = True
        # Validar fecha
        if form.fecha_termino.data < form.fecha_inicio.data:
            flash("La fecha de inicio no puede ser mayor a la fecha de termino.", "warning")
            es_valido = False
        # Validar registro repetido
        registro_repetido = (
            Incapacidad.query.filter_by(persona=incapacidad.persona)
            .filter_by(fecha_inicio=form.fecha_inicio.data)
            .filter_by(fecha_termino=form.fecha_termino.data)
            .filter_by(estatus="A")
            .filter(Incapacidad.id != incapacidad_id)
            .first()
        )
        if registro_repetido:
            flash("Esta persona ya tiene una incapacidad en la misma fecha de inicio y término.", "warning")
            es_valido = False
        if es_valido:
            # Buscar puesto en historial de puestos
            puesto_nombre = None
            historial_puesto = HistorialPuesto.query.filter_by(persona=incapacidad.persona).filter_by(estatus="A")
            historial_puesto = historial_puesto.filter(form.fecha_inicio.data >= HistorialPuesto.fecha_inicio)
            historial_puesto = historial_puesto.order_by(HistorialPuesto.fecha_inicio.desc()).first()
            if historial_puesto:
                puesto_nombre = historial_puesto.puesto_funcion.nombre
            # Guardar cambios
            incapacidad.fecha_inicio = form.fecha_inicio.data
            incapacidad.fecha_termino = form.fecha_termino.data
            incapacidad.clave_incapacidad = form.clave_incapacidad.data
            incapacidad.region = form.region.data
            incapacidad.motivo = safe_string(form.motivo.data, save_enie=True)
            incapacidad.puesto = puesto_nombre
            incapacidad.save()
            bitacora = Bitacora(
                modulo=Modulo.query.filter_by(nombre=MODULO).first(),
                usuario=current_user,
                descripcion=safe_message(f"Editado Incapacidad {incapacidad.motivo}"),
                url=url_for("incapacidades.detail", incapacidad_id=incapacidad.id),
            )
            bitacora.save()
            flash(bitacora.descripcion, "success")
            return redirect(bitacora.url)
    # Cargar valores leidos
    form.persona.data = incapacidad.persona.nombre_completo
    form.fecha_inicio.data = incapacidad.fecha_inicio
    form.fecha_termino.data = incapacidad.fecha_termino
    form.clave_incapacidad.data = incapacidad.clave_incapacidad
    form.region.data = incapacidad.region
    form.motivo.data = incapacidad.motivo
    return render_template("incapacidades/edit.jinja2", form=form, incapacidad=incapacidad)


@incapacidades.route("/incapacidades/eliminar/<int:incapacidad_id>")
@permission_required(MODULO, Permiso.ADMINISTRAR)
def delete(incapacidad_id):
    """Eliminar Incapacidad"""
    incapacidad = Incapacidad.query.get_or_404(incapacidad_id)
    if incapacidad.estatus == "A":
        incapacidad.delete()
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=safe_message(f"Eliminado Incapacidad {incapacidad.id}"),
            url=url_for("incapacidades.detail", incapacidad_id=incapacidad.id),
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
    return redirect(url_for("incapacidades.detail", incapacidad_id=incapacidad.id))


@incapacidades.route("/incapacidades/recuperar/<int:incapacidad_id>")
@permission_required(MODULO, Permiso.ADMINISTRAR)
def recover(incapacidad_id):
    """Recuperar Incapacidad"""
    incapacidad = Incapacidad.query.get_or_404(incapacidad_id)
    if incapacidad.estatus == "B":
        incapacidad.recover()
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=safe_message(f"Recuperado Incapacidad {incapacidad.id}"),
            url=url_for("incapacidades.detail", incapacidad_id=incapacidad.id),
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
    return redirect(url_for("incapacidades.detail", incapacidad_id=incapacidad.id))
