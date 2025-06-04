from flask import Flask, render_template, request, send_file
import pandas as pd
import os
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import random

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Globales para mantener el estado entre vistas
profesores_horarios_3 = []
profesores_horarios_2 = []
grupos_no_asignados = []

@app.route('/', methods=['GET', 'POST'])
def index():
    global profesores_horarios_3, profesores_horarios_2, grupos_no_asignados
    profesores_horarios_3 = []
    profesores_horarios_2 = []
    grupos_no_asignados = []
    estadisticas = {}
    error = None

    if request.method == 'POST':
        file = request.files.get('archivo')
        codigo = request.form.get('codigo', '').strip()

        if file and file.filename.endswith('.xlsx') and codigo:
            path = os.path.join(app.config['UPLOAD_FOLDER'], 'grupos.xlsx')
            file.save(path)
            df = pd.read_excel(path, dtype={'CodigoAsignatura': str})
            df = df[df['CodigoAsignatura'] == codigo]
            if df.empty:
                error = "No se encontraron grupos para ese código de asignatura."
                return render_template('index.html', estadisticas=estadisticas, profesores_3=[], profesores_2=[], grupos_no_asignados=[], error=error)

            columnas_necesarias = ['CodigoGrupo', 'Dia', 'Hora', 'Salon', 'Periodo', 'FacultadGrupo', 'Asignatura']
            for col in columnas_necesarias:
                if col not in df.columns:
                    error = f"El archivo Excel no tiene la columna '{col}'."
                    return render_template('index.html', estadisticas=estadisticas, profesores_3=[], profesores_2=[], grupos_no_asignados=[], error=error)

            df['HoraInicio'] = pd.to_datetime(df['Hora'].str.split('-').str[0].str.strip(), format='%I:%M %p')
            df['HoraFin'] = pd.to_datetime(df['Hora'].str.split('-').str[1].str.strip(), format='%I:%M %p')

            # === Agrupamiento auxiliar ===
            def bloque_valido(grupos):
                for dia in df['Dia'].unique():
                    subgrupos = [df[(df['CodigoGrupo'] == g) & (df['Dia'] == dia)] for g in grupos]
                    if sum(not sg.empty for sg in subgrupos) > 2:
                        return False
                    clases_dia = pd.concat(subgrupos)
                    if clases_dia.empty:
                        continue
                    clases_dia = clases_dia.sort_values('HoraInicio')
                    for i in range(len(clases_dia)):
                        for j in range(i + 1, len(clases_dia)):
                            ini1, fin1 = clases_dia.iloc[i]['HoraInicio'], clases_dia.iloc[i]['HoraFin']
                            ini2, fin2 = clases_dia.iloc[j]['HoraInicio'], clases_dia.iloc[j]['HoraFin']
                            if not (fin1 <= ini2 or ini1 >= fin2):
                                return False
                    for _, clase in clases_dia.iterrows():
                        fin = clase['HoraFin'].time()
                        if fin == datetime.strptime("12:45 PM", "%I:%M %p").time():
                            for _, otra in clases_dia.iterrows():
                                inicio = otra['HoraInicio'].time()
                                if inicio > fin and inicio < datetime.strptime("2:30 PM", "%I:%M %p").time():
                                    return False
                return True

            def crear_individuo(grupos, n):
                random.shuffle(grupos)
                return [grupos[i:i+n] for i in range(0, len(grupos) - len(grupos)%n, n)]

            def fitness(individuo, n):
                return sum(1 for b in individuo if len(b) == n and bloque_valido(b))

            def mutar(individuo, grupos_disp, n):
                nuevo = [b[:] for b in individuo]
                if not nuevo: return nuevo
                i, j = random.randint(0, len(nuevo)-1), random.randint(0, n-1)
                candidatos = [g for g in grupos_disp if g not in sum(nuevo, [])]
                if candidatos:
                    nuevo[i][j] = random.choice(candidatos)
                return nuevo

            def cruzar(p1, p2, n):
                corte = len(p1)//2
                hijo = p1[:corte] + p2[corte:]
                usados = set(sum(hijo, []))
                faltantes = list(set(df['CodigoGrupo'].unique()) - usados)
                random.shuffle(faltantes)
                for b in hijo:
                    while len(b) < n and faltantes:
                        b.append(faltantes.pop())
                return hijo

            def algoritmo_genetico(df, n=3, generaciones=30, tam_poblacion=20, grupos_filtrados=None):
                if grupos_filtrados is not None:
                    grupos = list(grupos_filtrados)
                else:
                    grupos = list(df['CodigoGrupo'].unique())
                poblacion = [crear_individuo(grupos[:], n) for _ in range(tam_poblacion)]
                for _ in range(generaciones):
                    puntuados = sorted([(fitness(ind, n), ind) for ind in poblacion], reverse=True)
                    seleccionados = [ind for _, ind in puntuados[:tam_poblacion//2]]
                    nueva_poblacion = seleccionados[:]
                    while len(nueva_poblacion) < tam_poblacion:
                        p1, p2 = random.sample(seleccionados, 2)
                        hijo = cruzar(p1, p2, n)
                        if random.random() < 0.3:
                            hijo = mutar(hijo, grupos, n)
                        nueva_poblacion.append(hijo)
                    poblacion = nueva_poblacion
                return max(poblacion, key=lambda ind: fitness(ind, n))

            # --- 1) Agrupa de a 3 ---
            mejor_individuo_3 = algoritmo_genetico(df, n=3)
            usados_3 = set()
            profesores_horarios_3 = []
            prof_index_3 = 1
            for bloque in mejor_individuo_3:
                bloque_sin_repetidos = []
                for grupo in bloque:
                    if grupo not in usados_3 and grupo not in bloque_sin_repetidos:
                        bloque_sin_repetidos.append(grupo)
                if len(bloque_sin_repetidos) == 3:
                    clases = []
                    for grupo in bloque_sin_repetidos:
                        usados_3.add(grupo)
                        clases += df[df['CodigoGrupo'] == grupo].to_dict('records')
                    profesores_horarios_3.append({
                        "profesor": f"Profesor {prof_index_3}",
                        "clases": clases
                    })
                    prof_index_3 += 1

            # --- 2) Agrupa de a 2 ---
            grupos_restantes = set(df['CodigoGrupo'].unique()) - usados_3
            profesores_horarios_2 = []
            usados_2 = set()
            # El índice de profesor para grupo de 2 continúa donde quedó el de grupo de 3
            prof_index_2 = prof_index_3
            if grupos_restantes:
                mejor_individuo_2 = algoritmo_genetico(df, n=2, grupos_filtrados=grupos_restantes)
                for bloque in mejor_individuo_2:
                    bloque_sin_repetidos = []
                    for grupo in bloque:
                        if grupo not in usados_3 and grupo not in usados_2 and grupo not in bloque_sin_repetidos:
                            bloque_sin_repetidos.append(grupo)
                    if len(bloque_sin_repetidos) == 2:
                        clases = []
                        for grupo in bloque_sin_repetidos:
                            usados_2.add(grupo)
                            clases += df[df['CodigoGrupo'] == grupo].to_dict('records')
                        profesores_horarios_2.append({
                            "profesor": f"Profesor {prof_index_2}",
                            "clases": clases
                        })
                        prof_index_2 += 1

            usados_final = usados_3 | usados_2

            # --- 3) No asignados ---
            todos = set(df['CodigoGrupo'].unique())
            grupos_no_asignados = df[df['CodigoGrupo'].isin(todos - usados_final)].to_dict('records')

            total = len(todos)
            asignados_3 = len(usados_3)
            asignados_2 = len(usados_2)
            no_asignados = total - asignados_3 - asignados_2
            nombre_materia = df['Asignatura'].iloc[0] if not df.empty else "Materia desconocida"

            estadisticas = {
                "total": total,
                "asignados_3": asignados_3,
                "asignados_2": asignados_2,
                "no_asignados": no_asignados,
                "nombre_asig": nombre_materia
            }

            return render_template('index.html',
                                estadisticas=estadisticas,
                                profesores_3=profesores_horarios_3,
                                profesores_2=profesores_horarios_2,
                                grupos_no_asignados=grupos_no_asignados,
                                error=error)

        else:
            error = "Archivo inválido o código vacío."
    # GET vacío
    return render_template('index.html', estadisticas=estadisticas, profesores_3=[], profesores_2=[], grupos_no_asignados=[], error=error)








@app.route('/descargar/<grupo>/<profesor>')
def descargar_pdf(grupo, profesor):
    global profesores_horarios_3, profesores_horarios_2

    if grupo == "3":
        lista_profes = profesores_horarios_3
    elif grupo == "2":
        lista_profes = profesores_horarios_2
    else:
        return "Tipo de grupo inválido", 400

    prof = next((p for p in lista_profes if p['profesor'] == profesor), None)
    if not prof:
        return "No encontrado", 404

    clases = prof['clases']
    if not clases:
        return "No hay clases para este profesor", 404

    grupo_data = clases[0]
    periodo = grupo_data['Periodo'].upper() + " SEMESTRE"
    facultad = grupo_data['FacultadGrupo'].upper()
    fecha_actual = datetime.now().strftime("%d-%m-%Y")

    # Asignaciones resumen
    asignaciones = {}
    asignaturas_resumen = []
    id_counter = 1
    for c in clases:
        key = (c.get('CodigoAsignatura', ''), c.get('Asignatura', ''), c.get('CodigoGrupo', ''))
        if key not in asignaciones:
            asignaciones[key] = str(id_counter)
            asignaturas_resumen.append({"id": str(id_counter), "codigo": key[0], "nombre": key[1], "grupo": key[2]})
            id_counter += 1

    dias = ['LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES']
    bloques_clase = sorted(set(c['Hora'] for c in clases), key=lambda h: pd.to_datetime(h.split('-')[0].strip(), format='%I:%M %p'))

    data = [['HORA'] + dias]
    for bloque in bloques_clase:
        fila = [bloque]
        hay_clase = False
        for dia in dias:
            clase = next((c for c in clases if c['Dia'].upper() == dia and c['Hora'] == bloque), None)
            if clase:
                key = (clase.get('CodigoAsignatura', ''), clase.get('Asignatura', ''), clase.get('CodigoGrupo', ''))
                val = f"{asignaciones[key]}\n({clase.get('Salon', '')})"
                fila.append(val)
                hay_clase = True
            else:
                fila.append('')
        if hay_clase:
            data.append(fila)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CenterBold', alignment=1, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='LeftBold', alignment=0, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='RightBold', alignment=2, fontName='Helvetica-Bold'))

    elements = [
        Paragraph("UNIVERSIDAD TECNOLÓGICA DE PANAMÁ", styles['CenterBold']),
        Paragraph("HORARIO DOCENTE", styles['CenterBold']),
        Paragraph("PANAMÁ", styles['CenterBold']),
        Spacer(1, 10)
    ]

    encabezado_info = [
        [Paragraph(f"NOMBRE: {profesor.upper()}", styles['LeftBold']),
         Paragraph(f"PROGRAMA: {facultad}", styles['RightBold'])],
        [Paragraph(f"IMPRESO: {fecha_actual}", styles['LeftBold']),
         Paragraph(f"PERIODO: {periodo}", styles['RightBold'])]
    ]
    encabezado_table = Table(encabezado_info, colWidths='*')
    encabezado_table.setStyle(TableStyle([('ALIGN', (0, 0), (0, -1), 'LEFT'),
                                          ('ALIGN', (1, 0), (1, -1), 'RIGHT')]))
    elements.append(encabezado_table)
    elements.append(Spacer(1, 10))

    tabla = Table(data, colWidths='*')
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.8, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    elements.append(tabla)
    elements.append(Spacer(1, 16))

    elements.append(Paragraph("ASIGNATURAS", styles['Heading3']))
    resumen_data = [["Identificador", "Asignatura", "Grupo"]] + [
        [r['id'], r['nombre'], r['grupo']] for r in asignaturas_resumen
    ]
    resumen = Table(resumen_data, colWidths='*')
    resumen.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.8, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    elements.append(resumen)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Horario_{profesor}.pdf", mimetype='application/pdf')






@app.route('/descargar_todos_asignados')
def descargar_todos_asignados():
    global profesores_horarios_3, profesores_horarios_2

    # 1. Recolectar TODAS las clases asignadas con su profesor
    all_clases = []
    for prof in profesores_horarios_3 + profesores_horarios_2:
        for clase in prof['clases']:
            all_clases.append({**clase, "Profesor": prof["profesor"]})

    # 2. Construir la tabla resumen y crear el diccionario de ids
    filas_resumen = []
    id_dict = {}
    vistos = set()
    for c in all_clases:
        clave = (c['CodigoGrupo'], c['CodigoAsignatura'], c['Asignatura'], c['Salon'], c['Profesor'])
        if clave not in vistos:
            filas_resumen.append([
                "",  # Se llenará con el No.
                c['CodigoGrupo'],
                c['CodigoAsignatura'] if 'CodigoAsignatura' in c else '',
                c['Asignatura'],
                c['Salon'],
                c['Profesor']
            ])
            vistos.add(clave)
    # Asignar el id (No.) y crear el diccionario para los grupos
    for idx, fila in enumerate(filas_resumen, 1):
        fila[0] = str(idx)
        id_dict[fila[1]] = str(idx)  # fila[1] = CodigoGrupo

    # 3. Matriz de horarios: obtener bloques y días
    dias = ['LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES']
    bloques_clase = sorted(
        set(c['Hora'] for c in all_clases),
        key=lambda h: pd.to_datetime(h.split('-')[0].strip(), format='%I:%M %p')
    )

    # 4. Construir la matriz tipo horario usando id_dict para el identificador
    data_horario = [['HORA'] + dias]
    for bloque in bloques_clase:
        fila = [bloque]
        for dia in dias:
            celdas = [c for c in all_clases if c['Dia'].upper() == dia and c['Hora'] == bloque]
            if celdas:
                textos = []
                for clase in celdas:
                    id_grupo = id_dict.get(clase['CodigoGrupo'], "")
                    texto = f"{id_grupo}"  # Solo el número, sin grupo ni salón
                    textos.append(texto)
                fila.append("\n".join(textos))
            else:
                fila.append('')
        data_horario.append(fila)

    # 5. Crear PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CenterBold', alignment=1, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='LeftBold', alignment=0, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='RightBold', alignment=2, fontName='Helvetica-Bold'))

    elements = [
        Paragraph("UNIVERSIDAD TECNOLÓGICA DE PANAMÁ", styles['CenterBold']),
        Paragraph("REPORTE DE TODOS LOS GRUPOS ASIGNADOS", styles['CenterBold']),
        Paragraph("PANAMÁ", styles['CenterBold']),
        Spacer(1, 10)
    ]

    # -- Ajusta los anchos de las columnas para que ambas tablas midan lo mismo (ejemplo: 720pt total) --
    horario_widths = [100, 124, 124, 124, 124, 124]  # 6 columnas = 720 puntos aprox
    resumen_widths = [35, 90, 60, 260, 80, 195]      # 6 columnas = 720 puntos aprox

    # 6A. Tabla de horario general
    elements.append(Paragraph("<b><i>HORARIO GENERAL</i></b>", styles['Heading3']))
    tabla_horario = Table(data_horario, colWidths=horario_widths)
    tabla_horario.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.8, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    elements.append(tabla_horario)
    elements.append(Spacer(1, 16))

    # 6B. Tabla resumen general
    elements.append(Paragraph("<b><i>RESUMEN DE GRUPOS ASIGNADOS</i></b>", styles['Heading3']))
    resumen_data2 = [["No.", "Grupo", "C. Asig.", "Asignatura", "Salón", "Profesor asignado"]]
    for fila in filas_resumen:
        resumen_data2.append(fila)
    resumen2 = Table(
        resumen_data2,
        colWidths=resumen_widths
    )
    resumen2.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.8, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    elements.append(resumen2)

    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Todos_Grupos_Asignados.pdf", mimetype='application/pdf')


if __name__ == '__main__':
    app.run(debug=True)
