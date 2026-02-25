# ==========================================
# fungi_sim.py  —  Version 3.1
# BSF Kühllager Gas-Simulator
# Projekt: Henke / Steyerberg  LP 640_07 Rev.02
# REPLOID Group AG  x  coolsulting: Michael Schäpers
#
# v3.1 Fixes:
#  - fillcolor: rgba() statt 8-stellige Hex (Plotly 5.x kompatibel)
#  - CO2 und NH3 Mastzyklus getrennte Diagramme
#  - Lüfterstufen-Schaltdiagramm
#  - Übersichtlicheres Layout, größere Charts
# ==========================================

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import time
import os
import base64
import io
from datetime import datetime

# reportlab wird lazy importiert — nur beim PDF-Button-Klick
# Installation falls nötig: pip install reportlab

def img_b64(path):
    if os.path.exists(path):
        with open(path,'rb') as f:
            return base64.b64encode(f.read()).decode()
    return None

# ── PDF REPORT GENERATOR ────────────────────────────────────
# Erweiterbar für beliebige Gase (CO2, NH3, CH4, H2S, VOC, ...)
# Gasparameter-Schema: {name, formula, rho, rate_avg, rate_unit, thresholds:[s1,s2,s3]}

def hex2rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2],16)/255.0 for i in (0,2,4))

def make_pdf_report(params: dict) -> bytes:
    """
    Generiert PDF-Bericht mit allen Simulationsparametern und Diagrammen.
    params: dict mit allen aktuellen Einstellungen aus der Streamlit-Session.
    Erweiterbar: params['gases'] = Liste von Gasparameter-Dicts.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                         TableStyle, HRFlowable, PageBreak,
                                         Image as RLImage)
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        raise ImportError(
            "reportlab nicht installiert.\n"
            "Bitte im Terminal ausführen:\n\n"
            "  pip install reportlab\n\n"
            "Dann Streamlit neu starten."
        )

    buf = io.BytesIO()
    W, H = A4  # 595 x 842 pt

    # ── Farben (ReportLab RGB 0-1) ──
    C_DARK   = colors.HexColor('#07090E')
    C_BLUE   = colors.HexColor('#36A9E1')
    C_GREEN  = colors.HexColor('#00C48C')
    C_ORANGE = colors.HexColor('#F5A623')
    C_RED    = colors.HexColor('#E84545')
    C_YELLOW = colors.HexColor('#FFD600')
    C_MUTED  = colors.HexColor('#4A6080')
    C_BORDER = colors.HexColor('#1C2D3F')
    C_WHITE  = colors.HexColor('#E2EEF8')
    C_MID    = colors.HexColor('#0D1520')

    # ── Styles ──
    ss = getSampleStyleSheet()
    def sty(name, **kw):
        kw.setdefault('textColor', C_WHITE)
        kw.setdefault('fontName', 'Helvetica')
        return ParagraphStyle(name, parent=ss['Normal'], **kw)

    S_TITLE   = sty('T', fontSize=22, textColor=C_BLUE,  spaceAfter=2, leading=26)
    S_SUB     = sty('S', fontSize=9,  textColor=C_MUTED, spaceAfter=8)
    S_H1      = sty('H1',fontSize=13, textColor=C_BLUE,  spaceBefore=10, spaceAfter=4,
                    fontName='Helvetica-Bold')
    S_H2      = sty('H2',fontSize=10, textColor=C_GREEN, spaceBefore=6, spaceAfter=3,
                    fontName='Helvetica-Bold')
    S_BODY    = sty('B', fontSize=8.5,textColor=C_WHITE, leading=13)
    S_MONO    = sty('M', fontSize=8,  textColor=C_BLUE,  fontName='Courier', leading=12)
    S_WARN    = sty('W', fontSize=8,  textColor=C_RED,   fontName='Helvetica-Bold')
    S_CAPTION = sty('C', fontSize=7.5,textColor=C_MUTED, alignment=TA_CENTER)

    def hr(col=C_BORDER): return HRFlowable(width='100%', thickness=0.5, color=col, spaceAfter=4, spaceBefore=4)

    def kv_table(rows, col_w=None):
        """Key-Value Tabelle mit dunklem Hintergrund"""
        cw = col_w or [55*mm, 110*mm]
        data = [[Paragraph(f"<b>{k}</b>", sty('k', fontSize=8, textColor=C_MUTED, fontName='Helvetica-Bold')),
                 Paragraph(str(v), sty('v', fontSize=8.5, textColor=C_WHITE))]
                for k, v in rows]
        t = Table(data, colWidths=cw)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,-1), C_MID),
            ('ROWBACKGROUNDS', (0,0),(-1,-1), [C_MID, C_DARK]),
            ('GRID', (0,0),(-1,-1), 0.3, C_BORDER),
            ('LEFTPADDING', (0,0),(-1,-1), 6),
            ('RIGHTPADDING',(0,0),(-1,-1), 6),
            ('TOPPADDING',  (0,0),(-1,-1), 4),
            ('BOTTOMPADDING',(0,0),(-1,-1), 4),
        ]))
        return t

    def stufen_table(stufen_data):
        """Lüfterstufen-Tabelle"""
        header = [Paragraph(h, sty('th', fontSize=8, textColor=C_MUTED, fontName='Helvetica-Bold', alignment=TA_CENTER))
                  for h in ['Stufe', 'CO<sub>2</sub> Schwelle', 'NH<sub>3</sub> Schwelle', 'Lüfter %', 'Lüfter m³/h (Z1)']]
        stage_cols = [C_MUTED, C_GREEN, C_ORANGE, C_RED]
        snames = ['ECO', 'STUFE 1', 'STUFE 2', 'ALARM']
        rows = [header]
        for i, (name, co2, nh3, pct, col) in enumerate(zip(snames,
            stufen_data['co2'], stufen_data['nh3'], stufen_data['pct'], stage_cols)):
            q1 = pct/100.0 * params['vol_z1'] * 6.0
            rows.append([
                Paragraph(f"<b>{name}</b>", sty(f's{i}', fontSize=8.5, textColor=col, fontName='Helvetica-Bold', alignment=TA_CENTER)),
                Paragraph(f"{co2:,} ppm", sty('cv', fontSize=8.5, textColor=C_WHITE, alignment=TA_CENTER)),
                Paragraph(f"{nh3} ppm",   sty('nv', fontSize=8.5, textColor=C_WHITE, alignment=TA_CENTER)),
                Paragraph(f"{pct} %",     sty('pv', fontSize=8.5, textColor=C_YELLOW,alignment=TA_CENTER)),
                Paragraph(f"{q1:.0f}",    sty('qv', fontSize=8.5, textColor=C_BLUE,  alignment=TA_CENTER)),
            ])
        t = Table(rows, colWidths=[30*mm, 38*mm, 38*mm, 24*mm, 36*mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,0), C_BORDER),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_MID, C_DARK]),
            ('GRID',(0,0),(-1,-1),0.3,C_BORDER),
            ('LEFTPADDING',(0,0),(-1,-1),5),
            ('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),4),
            ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
        return t

    def gas_chart_rl(gas_name, mass_kg, flow_pct, vol, rate_fn, rho, ambient,
                     thresholds, hours_arr, days_arr, mast_day,
                     rate_unit='g/kg/h', w=170*mm, h=60*mm):
        """
        Zeichnet Gas-Kurve direkt mit ReportLab — kein Plotly/Kaleido nötig.
        Erweiterbar für beliebige Gase: gas_name bestimmt Farbe.
        thresholds: [(ppm_val, label_str), ...]
        """
        from reportlab.graphics.shapes import (Drawing, Line, PolyLine, Rect,
                                                String, Group)
        from reportlab.graphics import renderPDF

        def _ppm(day):
            E_kg_h = mass_kg * rate_fn(day) / 1000.0
            E_m3_h = E_kg_h / rho
            Q = max(flow_pct/100.0 * vol * 6.0, 1.0)
            return ambient + (E_m3_h / Q) * 1e6

        arr = np.array([_ppm(d) for d in days_arr])
        h_now = (mast_day - 1.0) * 24.0
        val_now = _ppm(mast_day)

        # Farben je Gas
        gc_map = {'CO2':'#36A9E1','NH3':'#F5A623','CH4':'#FFD600',
                  'H2S':'#E84545','CO':'#00C48C','VOC':'#C084FC'}
        gc_hex = gc_map.get(gas_name, '#36A9E1')
        gc = colors.HexColor(gc_hex)

        thr_cols = [colors.HexColor('#00C48C'),
                    colors.HexColor('#F5A623'),
                    colors.HexColor('#E84545')]

        # Koordinatensystem
        PAD_L=32; PAD_R=52; PAD_B=18; PAD_T=14
        CW = w - PAD_L - PAD_R   # chart width in pt
        CH2= h - PAD_B - PAD_T   # chart height in pt

        y_max = max(float(arr.max()*1.15),
                    max(tv for tv,_ in thresholds)*1.1 if thresholds else 100)

        def px(hval): return PAD_L + (hval/288.0)*CW
        def py(ppm):  return PAD_B + (min(ppm,y_max)/y_max)*CH2

        d = Drawing(w, h)

        # Hintergrund
        d.add(Rect(0, 0, w, h, fillColor=colors.HexColor('#07090E'),
                   strokeColor=None))
        d.add(Rect(PAD_L, PAD_B, CW, CH2,
                   fillColor=colors.HexColor('#0D1520'), strokeColor=None))

        # Gitternetz + Stundenmarkierungen
        for hh, lbl in [(h, f'T{d}') for d,h in enumerate(range(0, 289, 24), 1)]:
            x = px(hh)
            d.add(Line(x, PAD_B, x, PAD_B+CH2,
                       strokeColor=colors.HexColor('#1C2D3F'),
                       strokeWidth=0.4, strokeDashArray=[2,3]))
            d.add(String(x+1, PAD_B-9, lbl,
                         fontSize=6, fillColor=colors.HexColor('#4A6080'),
                         fontName='Helvetica'))

        # Y-Achse Ticks (5 Stufen)
        for i in range(6):
            yv = y_max * i/5
            yp = py(yv)
            d.add(Line(PAD_L-2, yp, PAD_L+CW, yp,
                       strokeColor=colors.HexColor('#1C2D3F'),
                       strokeWidth=0.3))
            d.add(String(PAD_L-4, yp-3, f'{yv:.0f}',
                         fontSize=5.5, fillColor=colors.HexColor('#4A6080'),
                         fontName='Helvetica', textAnchor='end'))

        # Schwellenwert-Linien
        for (tv, tlbl), tc in zip(thresholds, thr_cols):
            if tv <= y_max:
                yp = py(tv)
                d.add(Line(PAD_L, yp, PAD_L+CW, yp,
                           strokeColor=tc, strokeWidth=0.8,
                           strokeDashArray=[4,3]))
                d.add(String(PAD_L+CW+3, yp-3, tlbl,
                             fontSize=5.5, fillColor=tc,
                             fontName='Helvetica'))

        # Füllbereich unter Kurve (vereinfacht: Rechteck-Approximation)
        fill_pts = []
        for i, (hv, pv) in enumerate(zip(hours_arr, arr)):
            fill_pts.extend([px(hv), py(0)])
        # Kurven-Polygon (Füllung)
        poly_pts = [px(hours_arr[0]), py(0)]
        for hv, pv in zip(hours_arr, arr):
            poly_pts.extend([px(hv), py(pv)])
        poly_pts.extend([px(hours_arr[-1]), py(0)])

        from reportlab.graphics.shapes import Polygon
        r,g,b = hex2rgb(gc_hex)
        d.add(Polygon(poly_pts,
                      fillColor=colors.Color(r,g,b,alpha=0.18),
                      strokeColor=None))

        # Kurve selbst
        curve_pts = []
        for hv, pv in zip(hours_arr, arr):
            curve_pts.extend([px(hv), py(pv)])
        d.add(PolyLine(curve_pts, strokeColor=gc, strokeWidth=1.8,
                       strokeLineJoin=1))

        # IST-Linie (Masttag)
        xnow = px(h_now)
        d.add(Line(xnow, PAD_B, xnow, PAD_B+CH2,
                   strokeColor=colors.HexColor('#FFD600'),
                   strokeWidth=1.0, strokeDashArray=[4,2]))
        ynow = py(val_now)
        d.add(String(xnow+2, ynow, f'{h_now:.0f}h: {val_now:.0f} ppm',
                     fontSize=6, fillColor=colors.HexColor('#FFD600'),
                     fontName='Courier'))

        # Peak-Annotation
        pidx = int(arr.argmax())
        peak_h = hours_arr[pidx]; peak_v = arr[pidx]
        peak_rate = rate_fn(days_arr[pidx])
        xp = px(peak_h); yp2 = py(peak_v)
        d.add(Line(xp, yp2, xp, yp2+10,
                   strokeColor=gc, strokeWidth=0.8))
        lbl_txt = f'{peak_v:.0f} ppm  {peak_rate:.4f} {rate_unit}'
        d.add(String(xp, yp2+11, lbl_txt,
                     fontSize=6, fillColor=gc,
                     fontName='Courier', textAnchor='middle'))

        # Achsenbeschriftung
        d.add(String(PAD_L+CW/2, 2, 'Stunden [h]',
                     fontSize=6, fillColor=colors.HexColor('#7A9CC0'),
                     fontName='Helvetica', textAnchor='middle'))
        d.add(String(8, PAD_B+CH2/2, 'ppm',
                     fontSize=6, fillColor=colors.HexColor('#7A9CC0'),
                     fontName='Helvetica', textAnchor='middle'))

        return d

    # ── PAGE TEMPLATE ──────────────────────────────
    # Logo-Pfade
    _logo_cs  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coolsulting_logo_white.png')                 if '__file__' in dir() else 'coolsulting_logo_white.png'
    # Fallback für Streamlit Cloud
    import glob
    _logo_candidates = glob.glob('**/coolsulting_logo_white.png', recursive=True) + ['coolsulting_logo_white.png']
    _logo_cs = next((p for p in _logo_candidates if os.path.exists(p)), None)

    HEADER_H = 16*mm  # höhere Kopfzeile gegen Overlap
    FOOTER_H = 22*mm  # Fußzeile mit Firmenadressen

    def on_page(canv, doc):
        canv.saveState()
        # Dunkler Hintergrund
        canv.setFillColor(C_DARK)
        canv.rect(0, 0, W, H, fill=1, stroke=0)

        # ── KOPFZEILE ──────────────────────────────────
        canv.setFillColor(colors.HexColor('#0D1520'))
        canv.rect(0, H-HEADER_H, W, HEADER_H, fill=1, stroke=0)
        canv.setStrokeColor(C_BLUE)
        canv.setLineWidth(1.5)
        canv.line(0, H-HEADER_H, W, H-HEADER_H)

        # Titel links
        canv.setFillColor(C_BLUE)
        canv.setFont('Helvetica-Bold', 9)
        canv.drawString(15*mm, H-7*mm, 'BSF KÜHLLAGER GAS-SIMULATOR')
        canv.setFillColor(C_MUTED)
        canv.setFont('Helvetica', 7)
        canv.drawString(15*mm, H-12*mm, f'LP 640_07 Rev.02  ·  {params["date"]}  ·  Seite {doc.page}')



        # ── FUSSZEILE ──────────────────────────────────
        canv.setFillColor(colors.HexColor('#0D1520'))
        canv.rect(0, 0, W, FOOTER_H, fill=1, stroke=0)
        canv.setStrokeColor(C_BORDER)
        canv.setLineWidth(0.5)
        canv.line(0, FOOTER_H, W, FOOTER_H)

        # Firmenblock links: Polar Energy
        canv.setFillColor(C_MUTED)
        canv.setFont('Helvetica-Bold', 6.5)
        canv.drawString(15*mm, FOOTER_H-5*mm, 'In Zusammenarbeit mit:')
        canv.setFont('Helvetica-Bold', 6.5)
        canv.setFillColor(C_WHITE)
        canv.drawString(15*mm, FOOTER_H-10*mm, 'Polar Energy Leithinger GmbH')
        canv.setFont('Helvetica', 6)
        canv.setFillColor(C_MUTED)
        canv.drawString(15*mm, FOOTER_H-14.5*mm, 'Dr.-Gross-Str. 36-38 · 4600 Wels')
        canv.drawString(15*mm, FOOTER_H-18.5*mm, 'office@polar-energy.at')

        # Trennlinie Mitte
        canv.setStrokeColor(C_BORDER)
        canv.line(W/2-20*mm, 2*mm, W/2-20*mm, FOOTER_H-2*mm)

        # Firmenblock Mitte: coolsulting
        canv.setFont('Helvetica-Bold', 6.5)
        canv.setFillColor(C_WHITE)
        canv.drawString(W/2-18*mm, FOOTER_H-10*mm, 'Coolsulting e.U.')
        canv.setFont('Helvetica', 6)
        canv.setFillColor(C_MUTED)
        canv.drawString(W/2-18*mm, FOOTER_H-14.5*mm, 'Mozartstrasse 11 · 4020 Linz, Österreich')



        # Copyright + Seitennum
        canv.setFont('Helvetica', 6)
        canv.setFillColor(C_MUTED)
        canv.drawCentredString(W/2+25*mm, FOOTER_H-10*mm, f'Seite {doc.page}')
        canv.drawCentredString(W/2+25*mm, FOOTER_H-15*mm, '© coolsulting e.U.')
        canv.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=HEADER_H+4*mm, bottomMargin=FOOTER_H+4*mm)

    story = []
    p = params

    # ════════════════════════════════════════════
    # SEITE 1 — DECKBLATT + ZUSAMMENFASSUNG
    # ════════════════════════════════════════════
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph('BSF KÜHLLAGER', sty('TT', fontSize=28, textColor=C_BLUE,
                            fontName='Helvetica-Bold', spaceAfter=1, leading=32)))
    story.append(Paragraph('GAS-SIMULATIONS-BERICHT',
                            sty('T2', fontSize=20, textColor=C_WHITE,
                                fontName='Helvetica-Bold', spaceAfter=6, leading=24)))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(f'Projekt: Henke / Steyerberg  ·  LP 640_07 Rev.02',
                            sty('PS', fontSize=9, textColor=C_MUTED, spaceAfter=3)))
    story.append(Paragraph(f'Erstellt: {p["date"]}  ·  Masttag: {p["mast_day"]:.1f} / 8  ·  Simulator v5.0',
                            sty('PS2', fontSize=9, textColor=C_MUTED, spaceAfter=6)))
    story.append(hr(C_BLUE))
    story.append(Spacer(1, 4*mm))

    # STATUS-AMPEL
    def status_pill(label, val, unit, warn_col):
        col = C_RED if warn_col == 'red' else (C_ORANGE if warn_col == 'orange' else C_GREEN)
        return Paragraph(f'<b>{label}</b>: <font color="#{col.hexval()[1:]}">{val} {unit}</font>',
            sty('pill', fontSize=9, textColor=C_WHITE))

    # KPI-Tabelle Seite 1
    co2_z1_now = p['co2_z1']; nh3_z1_now = p['nh3_z1']
    co2_z2_now = p['co2_z2']; nh3_z2_now = p['nh3_z2']
    def co2_warn(v): return 'red' if v>p['co2_s3'] else ('orange' if v>p['co2_s2'] else ('yellow' if v>p['co2_s1'] else 'green'))
    def nh3_warn(v): return 'red' if v>p['nh3_s3'] else ('orange' if v>p['nh3_s2'] else ('yellow' if v>p['nh3_s1'] else 'green'))

    kpi_data = [
        [Paragraph('<b>PARAMETER</b>', sty('kh0', fontSize=8, textColor=C_MUTED, fontName='Helvetica-Bold', alignment=TA_LEFT)),
         Paragraph('<b>ZONE 01</b>', sty('kh0z1', fontSize=8, textColor=C_MUTED, fontName='Helvetica-Bold', alignment=TA_CENTER)),
         Paragraph('<b>ZONE 02</b>', sty('kh0z2', fontSize=8, textColor=C_MUTED, fontName='Helvetica-Bold', alignment=TA_CENTER))],
        [Paragraph('<b>CO<sub>2</sub> [ppm]</b>', sty('kh',fontSize=9,textColor=C_MUTED,alignment=TA_LEFT)),
         Paragraph(f'<b>{co2_z1_now:.0f}</b>', sty('kv1',fontSize=12,textColor=C_BLUE,fontName='Helvetica-Bold')),
         Paragraph(f'<b>{co2_z2_now:.0f}</b>', sty('kv2',fontSize=12,textColor=C_GREEN,fontName='Helvetica-Bold'))],
        [Paragraph('<b>NH<sub>3</sub> [ppm]</b>', sty('kh2',fontSize=9,textColor=C_MUTED,alignment=TA_LEFT)),
         Paragraph(f'<b>{nh3_z1_now:.1f}</b>', sty('kv3',fontSize=12,textColor=C_ORANGE,fontName='Helvetica-Bold')),
         Paragraph(f'<b>{nh3_z2_now:.1f}</b>', sty('kv4',fontSize=12,textColor=C_YELLOW,fontName='Helvetica-Bold'))],
        [Paragraph('<b>Lüfter m³/h</b>', sty('kh3',fontSize=9,textColor=C_MUTED,alignment=TA_LEFT)),
         Paragraph(f'{p["q1"]:.0f} m³/h  ({p["flow_z1"]:.0f}%)', sty('kv5',fontSize=9,textColor=C_WHITE)),
         Paragraph(f'{p["q2"]:.0f} m³/h', sty('kv6',fontSize=9,textColor=C_WHITE))],
        [Paragraph('<b>Larvenmasse</b>', sty('kh4',fontSize=9,textColor=C_MUTED,alignment=TA_LEFT)),
         Paragraph(f'{p["mass_z1"]:.1f} t', sty('kv7',fontSize=9,textColor=C_WHITE)),
         Paragraph(f'{p["mass_z2"]:.1f} t', sty('kv8',fontSize=9,textColor=C_WHITE))],
        [Paragraph('<b>Raumvolumen</b>', sty('kh5',fontSize=9,textColor=C_MUTED,alignment=TA_LEFT)),
         Paragraph(f'{p["vol_z1"]:.1f} m³', sty('kv9',fontSize=9,textColor=C_WHITE)),
         Paragraph(f'{p["vol_z2"]:.1f} m³', sty('kv10',fontSize=9,textColor=C_WHITE))],
        [Paragraph('<b>ACH</b>', sty('kh6',fontSize=9,textColor=C_MUTED,alignment=TA_LEFT)),
         Paragraph(f'{p["ach_z1"]:.2f} h⁻¹', sty('kv11',fontSize=9,textColor=C_WHITE)),
         Paragraph(f'{p["ach_z2"]:.2f} h⁻¹', sty('kv12',fontSize=9,textColor=C_WHITE))],
    ]
    kpi_t = Table(kpi_data, colWidths=[50*mm, 80*mm, 46*mm])
    kpi_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),C_BORDER),
        ('TEXTCOLOR',(0,0),(-1,0),C_MUTED),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,0),8),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_MID, C_DARK]),
        ('GRID',(0,0),(-1,-1),0.3,C_BORDER),
        ('LEFTPADDING',(0,0),(-1,-1),7),
        ('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),7),
        ('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),   # ALLE zentriert
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        # Erste Spalte (Labels) linksbündig
        ('ALIGN',(0,1),(0,-1),'LEFT'),
    ]))
    story.append(kpi_t)
    story.append(Spacer(1, 5*mm))

    # ── RAUMPARAMETER ──
    story.append(Paragraph('RAUMPARAMETER', S_H1))
    story.append(hr())
    story.append(kv_table([
        ('Zone 01 — Abmessungen', f'{p["z1_l"]:.3f} × {p["z1_b"]:.3f} × {p["z1_h"]:.3f} m  =  {p["vol_z1"]:.1f} m³'),
        ('Zone 02 — Abmessungen', f'{p["z2_l"]:.3f} × {p["z2_b"]:.3f} × {p["z2_h"]:.3f} m  =  {p["vol_z2"]:.1f} m³'),
        ('Zone 01 — Max. Lüfter', f'{p["fan_z1_max"]:.0f} m³/h bei 100% (6 ACH)'),
        ('Zone 02 — Max. Lüfter', f'{p["fan_z2_max"]:.0f} m³/h bei 100%'),
        ('Substrat Zone 01', f'{p["boxes_z1"]} Boxen × {p["box_kg_z1"]} kg = {p["mass_z1_kg"]:.0f} kg'),
        ('Substrat Zone 02', f'{p["boxes_z2"]} Boxen × {p["box_kg_z2"]} kg = {p["mass_z2_kg"]:.0f} kg'),
    ]))
    story.append(Spacer(1, 4*mm))

    # ── EMISSIONSRATEN ──
    story.append(Paragraph('EMISSIONSRATEN & GASPARAMETER', S_H1))
    story.append(hr())

    # Erweiterbare Gastabelle — für zukünftige Gase
    gas_header = ['Gas', 'Formel', 'Dichte kg/m³', 'Basisrate', 'Kurvenform', 'Verhalten']
    gas_rows = [
        ['CO<sub>2</sub>', 'CO<sub>2</sub>', '1.842', f'{p["co2_rate"]:.3f} g/kg/h (Ø)', 'Glocke (Tag 4 Peak)', 'Schwerer als Luft → bodennah'],
        ['NH<sub>3</sub>',  'NH<sub>3</sub>', '0.769', f'{p["nh3_rate"]:.5f} g/kg/h (Basis)', 'Exponentiell ab Tag 4', 'Leichter als Luft → deckennah'],
        ['CH<sub>4</sub>',  'CH<sub>4</sub>', '0.657', '— (ausstehend)',      'Exponentiell',    'Leichter als Luft (zukünftig)'],
        ['H<sub>2</sub>S',  'H<sub>2</sub>S', '1.363', '— (ausstehend)',      'Exponentiell',    'Schwerer als Luft (zukünftig)'],
    ]
    gas_cols_w = [16*mm, 14*mm, 22*mm, 38*mm, 35*mm, 51*mm]
    gas_t_data = [[Paragraph(h, sty(f'gh{i}', fontSize=7.5, textColor=C_MUTED, fontName='Helvetica-Bold'))
                   for i,h in enumerate(gas_header)]]
    for row in gas_rows:
        gas_t_data.append([Paragraph(c, sty(f'gc', fontSize=7.5, textColor=C_WHITE)) for c in row])
    gas_t = Table(gas_t_data, colWidths=gas_cols_w)
    gas_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),C_BORDER),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_MID,C_DARK]),
        ('GRID',(0,0),(-1,-1),0.3,C_BORDER),
        ('LEFTPADDING',(0,0),(-1,-1),5),
        ('TOPPADDING',(0,0),(-1,-1),3),
        ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('TEXTCOLOR',(0,1),(1,-1),C_BLUE),
    ]))
    story.append(gas_t)
    story.append(Spacer(1, 4*mm))

    # ── LÜFTERSTUFEN ──
    story.append(Paragraph('LÜFTERSTUFEN — SCHALTPUNKTE', S_H1))
    story.append(hr())
    story.append(stufen_table(p['stufen']))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        'Die Lüfterstufen schalten automatisch wenn CO<sub>2</sub> ODER NH<sub>3</sub> den '
        'jeweiligen Schwellwert überschreiten (OR-Logik). '
        'ALARM-Stufe bleibt aktiv bis beide Gase unter S2-Schwelle fallen.',
        sty('note', fontSize=7.5, textColor=C_MUTED)))

    story.append(PageBreak())

    # ════════════════════════════════════════════
    # SEITE 2 — DIAGRAMME ZONE 01
    # ════════════════════════════════════════════
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph('ZONE 01 — DIAGRAMME', S_H1))
    story.append(Paragraph(
        f'Larvenmasse: {p["mass_z1"]:.1f} t  ·  Lüfter: {p["flow_z1"]:.0f}%  ·  {p["q1"]:.0f} m³/h  ·  {p["ach_z1"]:.2f} ACH  ·  Masttag: {p["mast_day"]:.1f}',
        S_SUB))
    story.append(hr())

    hours_arr = np.linspace(0, 288, 400)
    days_arr  = 1.0 + hours_arr / 24.0

    import math
    def _co2_rate(day, r=None):
        ra = r or p['co2_rate']
        x = day/8.0
        return ra * (0.3 + 2.7 * math.sin(math.pi*x)**1.8)
    def _nh3_rate(day, b=None):
        ba = b or p['nh3_rate']
        x = day/8.0
        if x < 0.45: return ba*(1.0+0.5*x/0.45)
        return ba*1.5*math.exp(2.6*(x-0.45))

    # CO2 Z1 Chart
    story.append(Paragraph('CO<sub>2</sub> — Zone 01 [ppm]', S_H2))
    story.append(gas_chart_rl('CO2', p['mass_z1']*1000, p['flow_z1'], p['vol_z1'],
        _co2_rate, 1.842, 420.0,
        [(p['co2_s1'], f'{p["co2_s1"]:,} ppm'),
         (p['co2_s2'], f'{p["co2_s2"]:,} ppm'),
         (p['co2_s3'], f'{p["co2_s3"]:,} ppm — ALARM')],
        hours_arr, days_arr, p['mast_day'], rate_unit='g/kg/h'))
    story.append(Spacer(1, 3*mm))

    # NH3 Z1 Chart
    story.append(Paragraph('NH<sub>3</sub> — Zone 01 [ppm]  (exponentiell ab Stunde 72)', S_H2))
    story.append(gas_chart_rl('NH3', p['mass_z1']*1000, p['flow_z1'], p['vol_z1'],
        _nh3_rate, 0.769, 0.02,
        [(p['nh3_s1'], f'{p["nh3_s1"]} ppm'),
         (p['nh3_s2'], f'{p["nh3_s2"]} ppm'),
         (p['nh3_s3'], f'{p["nh3_s3"]} ppm — ALARM')],
        hours_arr, days_arr, p['mast_day'], rate_unit='mg/kg/h'))
    story.append(Spacer(1, 3*mm))

    # Kubaturberechnung Z1
    story.append(Paragraph('KUBATURBERECHNUNG — ZONE 01', S_H2))
    story.append(hr())
    ach_z1 = p['q1'] / p['vol_z1']
    story.append(kv_table([
        ('Raumvolumen Z1',       f'{p["vol_z1"]:.2f} m³'),
        ('Volumenstrom aktuell', f'{p["q1"]:.0f} m³/h  ({p["flow_z1"]:.0f}%)'),
        ('Luftwechsel (ACH)',    f'{ach_z1:.2f} h⁻¹  =  alle {60/ach_z1:.1f} Minuten'),
        ('CO<sub>2</sub> aktuell', f'{p["co2_z1"]:.0f} ppm  →  {p["co2_z1"]/1e6*p["vol_z1"]*1.842:.3f} kg CO<sub>2</sub> im Raum'),
        ('NH<sub>3</sub> aktuell', f'{p["nh3_z1"]:.1f} ppm  →  {p["nh3_z1"]/1e6*p["vol_z1"]*0.769:.4f} kg NH<sub>3</sub> im Raum'),
        ('Massenbilanz-Formel',  'c_ppm = c_aussen + (E_m3/h ÷ Q_m3/h) × 10⁶'),
    ]))

    story.append(PageBreak())

    # ════════════════════════════════════════════
    # SEITE 3 — DIAGRAMME ZONE 02
    # ════════════════════════════════════════════
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph('ZONE 02 — DIAGRAMME', S_H1))
    story.append(Paragraph(
        f'Larvenmasse: {p["mass_z2"]:.1f} t  ·  Lüfter: {p["q2"]:.0f} m³/h  ·  {p["ach_z2"]:.2f} ACH  ·  Masttag: {p["mast_day"]:.1f}',
        S_SUB))
    story.append(hr())

    story.append(Paragraph('CO<sub>2</sub> — Zone 02 [ppm]', S_H2))
    story.append(gas_chart_rl('CO2', p['mass_z2']*1000, p['flow_z2'], p['vol_z2'],
        _co2_rate, 1.842, 420.0,
        [(p['co2_s1'], f'{p["co2_s1"]:,} ppm'),
         (p['co2_s2'], f'{p["co2_s2"]:,} ppm'),
         (p['co2_s3'], f'{p["co2_s3"]:,} ppm — ALARM')],
        hours_arr, days_arr, p['mast_day'], rate_unit='g/kg/h'))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph('NH<sub>3</sub> — Zone 02 [ppm]  (exponentiell ab Stunde 72)', S_H2))
    story.append(gas_chart_rl('NH3', p['mass_z2']*1000, p['flow_z2'], p['vol_z2'],
        _nh3_rate, 0.769, 0.02,
        [(p['nh3_s1'], f'{p["nh3_s1"]} ppm'),
         (p['nh3_s2'], f'{p["nh3_s2"]} ppm'),
         (p['nh3_s3'], f'{p["nh3_s3"]} ppm — ALARM')],
        hours_arr, days_arr, p['mast_day'], rate_unit='mg/kg/h'))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph('KUBATURBERECHNUNG — ZONE 02', S_H2))
    story.append(hr())
    ach_z2 = p['q2'] / p['vol_z2']
    story.append(kv_table([
        ('Raumvolumen Z2',       f'{p["vol_z2"]:.2f} m³'),
        ('Volumenstrom aktuell', f'{p["q2"]:.0f} m³/h  ({p["flow_z2"]:.0f}%)'),
        ('Luftwechsel (ACH)',    f'{ach_z2:.2f} h⁻¹  =  alle {60/ach_z2:.1f} Minuten'),
        ('CO<sub>2</sub> aktuell', f'{p["co2_z2"]:.0f} ppm  →  {p["co2_z2"]/1e6*p["vol_z2"]*1.842:.4f} kg CO<sub>2</sub> im Raum'),
        ('NH<sub>3</sub> aktuell', f'{p["nh3_z2"]:.1f} ppm  →  {p["nh3_z2"]/1e6*p["vol_z2"]*0.769:.5f} kg NH<sub>3</sub> im Raum'),
        ('Max. Lüfter Z2',      f'{p["fan_z2_max"]:.0f} m³/h  (Auslegung)'),
    ]))
    story.append(Spacer(1, 5*mm))

    # ── ERWEITERUNGSHINWEIS ──
    story.append(hr(C_BLUE))
    story.append(Paragraph('ERWEITERUNGSMÖGLICHKEITEN', S_H1))
    story.append(Spacer(1, 2*mm))
    ext_text = (
        'Dieser Bericht ist für weitere Gase vorbereitet. Die Funktion <font face="Courier">gas_chart_image()</font> '
        'akzeptiert beliebige Gase mit eigenem Dichte-Parameter (rho), eigener Emissionsrate und '
        'eigenen Schwellwerten. Folgende Gase sind für zukünftige Erweiterungen vorgesehen:<br/><br/>'
        '• <b>CH<sub>4</sub> (Methan):</b> Rho 0.657 kg/m³, LEL 4.4 Vol%, zukünftige Gasgenerator-Einheiten<br/>'
        '• <b>H<sub>2</sub>S (Schwefelwasserstoff):</b> Rho 1.363 kg/m³, MAK 1 ppm, Warnschwelle BSF 5 ppm<br/>'
        '• <b>CO (Kohlenmonoxid):</b> Rho 1.165 kg/m³, MAK 30 ppm<br/>'
        '• <b>VOC (flüchtige organische Verbindungen):</b> projektspezifisch<br/><br/>'
        'Kubaturberechnung: Pro Gas wird die Massenbilanz-Gleichung '
        '<font face="Courier">c = c_amb + (E/Q) × 10⁶</font> angewendet, '
        'wobei E = Emissionsrate in m³/h (aus g/kg/h ÷ Gasdichte) und '
        'Q = Volumenstrom des Lüfters in m³/h.'
    )
    story.append(Paragraph(ext_text, sty('ext', fontSize=8, textColor=C_WHITE, leading=13)))

    # ════════════════════════════════════════════
    # HAFTUNGSAUSSCHLUSS
    # ════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph('HAFTUNGSAUSSCHLUSS', sty('HA_T', fontSize=14,
                            textColor=C_RED, fontName='Helvetica-Bold', spaceAfter=4)))
    story.append(hr(C_RED))
    story.append(Spacer(1, 3*mm))

    disclaimer_paragraphs = [
        ('Allgemeines',
         'Dieser Bericht wurde auf Basis der BSF Gas-Simulationssoftware v5.0 erstellt und dient '
         'ausschliesslich zu Planungs- und Informationszwecken. Die dargestellten Werte sind '
         'Simulationsergebnisse auf Basis wissenschaftlicher Emissionsmodelle (Global 2000, 2024; '
         'Chen et al., 2019) und erheben keinen Anspruch auf Vollständigkeit oder absolute Genauigkeit.'),
        ('Keine Gewährleistung',
         'Polar Energy Leithinger GmbH und Coolsulting e.U. übernehmen keine Haftung für Schäden, '
         'die aus der Verwendung dieser Simulationsergebnisse entstehen. Die tatsächlichen '
         'Gaswerte in der Anlage können von den simulierten Werten abweichen und müssen durch '
         'geeignete Messinstrumente (zugelassene Gassensoren) kontinuierlich überwacht werden.'),
        ('Sicherheitshinweis',
         'NH3 (Ammoniak) ist ab 25 ppm gesundheitsschädlich (MAK-Wert) und ab 300 ppm '
         'lebensgefährlich. CO2 wirkt ab 5.000 ppm narkotisierend und ab 10.000 ppm '
         'lebensbedrohlich. Der Betrieb der Anlage erfordert zwingend den Einsatz kalibrierter '
         'Gassensoren, geeigneter Schutzausrüstung und ausgebildeten Fachpersonals. '
         'Bei Überschreitung der ALARM-Schwellen ist die Anlage sofort zu evakuieren.'),
        ('Datenschutz & Vertraulichkeit',
         'Dieser Bericht enthält vertrauliche Projektinformationen. Weitergabe an Dritte nur '
         'mit ausdrücklicher schriftlicher Genehmigung von Polar Energy Leithinger GmbH '
         'und Coolsulting e.U.'),
        ('Urheberrecht',
         '© Coolsulting e.U. — Mozartstrasse 11, 4020 Linz, Österreich. '
         'Alle Rechte vorbehalten. Die BSF Gas-Simulationssoftware und dieser Bericht '
         'sind urheberrechtlich geschützt. Vervielfältigung, Bearbeitung oder Verbreitung '
         'ohne ausdrückliche Genehmigung ist untersagt.'),
    ]

    for title, text in disclaimer_paragraphs:
        story.append(Paragraph(title, sty('dh', fontSize=9, textColor=C_ORANGE,
                                fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=2)))
        story.append(Paragraph(text, sty('db', fontSize=8, textColor=C_WHITE,
                                leading=12, spaceAfter=4)))

    story.append(Spacer(1, 6*mm))
    story.append(hr(C_BORDER))
    story.append(Spacer(1, 3*mm))
    # Signaturen
    sig_data = [[
        Paragraph('Erstellt durch:', sty('sl', fontSize=8, textColor=C_MUTED)),
        Paragraph('Geprüft durch:', sty('sl2', fontSize=8, textColor=C_MUTED)),
        Paragraph('Datum:', sty('sl3', fontSize=8, textColor=C_MUTED)),
    ],[
        Paragraph('____________________________', sty('sl4', fontSize=8, textColor=C_WHITE)),
        Paragraph('____________________________', sty('sl5', fontSize=8, textColor=C_WHITE)),
        Paragraph(p["date"][:10], sty('sl6', fontSize=8, textColor=C_WHITE)),
    ],[
        Paragraph('Coolsulting e.U.', sty('sl7', fontSize=7.5, textColor=C_MUTED)),
        Paragraph('Polar Energy Leithinger GmbH', sty('sl8', fontSize=7.5, textColor=C_MUTED)),
        Paragraph('', sty('sl9', fontSize=7.5, textColor=C_MUTED)),
    ]]
    sig_t = Table(sig_data, colWidths=[60*mm, 70*mm, 46*mm])
    sig_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), C_DARK),
        ('GRID',(0,0),(-1,-1),0,colors.white),
        ('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),8),
    ]))
    story.append(sig_t)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


# ── PDF BUTTON IN SIDEBAR ────────────────────────────────────
# ── DESIGN ──────────────────────────────────────────────────
BLUE   = "#36A9E1"
GREEN  = "#6EE87A"
YELLOW = "#FFD166"
RED    = "#EF476F"
ORANGE = "#FF9B42"
DARK   = "#07090E"
CARD   = "#0D1520"
CARD2  = "#0A1218"
BORDER = "#152030"
WHITE  = "#D8E8F4"
MUTED  = "#2C4560"

# rgba() Hilfsfunktionen (Plotly-kompatibel, kein 8-stelliger Hex!)
def rgba_blue(a=0.12):  return f"rgba(54,169,225,{a})"
def rgba_green(a=0.12): return f"rgba(110,232,122,{a})"
def rgba_red(a=0.12):   return f"rgba(239,71,111,{a})"
def rgba_orange(a=0.12):return f"rgba(255,155,66,{a})"
def rgba_yellow(a=0.12):return f"rgba(255,209,102,{a})"

# ── RAUMPARAMETER (LP 640_07 Rev.02) ────────────────────────
Z1_L, Z1_B, Z1_H = 21.359, 9.750, 3.800
Z2_L, Z2_B, Z2_H =  3.800, 2.900, 3.800
VOL_Z1 = Z1_L * Z1_B * Z1_H   # 790.7 m³
VOL_Z2 = Z2_L * Z2_B * Z2_H   # 42.0 m³
Z1_LARVEN_MAX = 51_858  # kg Substrat Zone 01 (201 Boxen × 258 kg)
Z2_LARVEN_MAX =  7_560  # kg Substrat Zone 02 (63 Boxen × 120 kg)

# ── PHYSIKALISCHE KONSTANTEN ─────────────────────────────────
RHO_AIR = 1.225   # kg/m³ Luft bei 10°C
RHO_CO2 = 1.842   # kg/m³ CO2 (schwerer als Luft → bodennah)
RHO_NH3 = 0.769   # kg/m³ NH3 (leichter als Luft → deckennah)
CO2_AMBIENT = 420.0   # ppm CO2 Außenluft

# ── LÜFTER-AUSLEGUNG ─────────────────────────────────────────
# 100% = Nennvolumenstrom — ausgelegt für max. 6 ACH Zone 01
FAN_Z1_MAX_M3H = 60000.0         # Auslegungsmaximum Zone 01 für Simulation
FAN_Z2_MAX_M3H = 60000.0         # Auslegungsmaximum Zone 02 für Simulation

def fan_m3h(pct, vol, max_q=None):
    """Volumenstrom in m³/h bei gegebener Lüfterprozent und Raumvolumen"""
    if max_q is None:
        max_q = vol * 6.0
    return max(pct / 100.0 * max_q, 1.0)

def fan_m3h_z2(pct):
    """Zone 02: max. FAN_Z2_MAX_M3H bei 100%"""
    return fan_m3h(pct, VOL_Z2, FAN_Z2_MAX_M3H)

def ach_val(pct, vol, max_q=None):
    """Luftwechsel pro Stunde"""
    return round(fan_m3h(pct, vol, max_q) / vol, 2)

# ── BSF-EMISSIONSRATEN ───────────────────────────────────────
# Quelle: Global 2000 (2024): 1414 g CO2/kg Substrat über 8 Tage
# Normiert auf g CO2 / kg Substrat / h, Gauskurve über 8 Tage
CO2_DAYS        = 8
CO2_RATE_AVG    = 0.125  # g CO2/kg/h (Durchschnitt → passt zu 1414g/kg/8d/24h ÷ Faktor Trockensubstanz)
CO2_RATE_PEAK   = 0.38   # g CO2/kg/h (Peak Tag 4)
# NH3: exponentieller Anstieg ab Tag 4 (Chen et al. 2019)
NH3_RATE_BASE   = 0.001   # g NH3/kg/h = 1 mg/kg/h (Tag 1) — realistischer BSF-Ausstoss, Peak Tag 8 ca. 6 mg/kg/h
NH3_RATE_PEAK   = 0.00627 # g NH3/kg/h = 6.27 mg/kg/h (Tag 8 Peak bei Base 0.001)

# ── GRENZWERTE (Arbeitsschutz + Prozess) ─────────────────────
CO2_OPT = 1_000;  CO2_S1 = 3_000;  CO2_S2 = 5_000;  CO2_S3 = 10_000  # ppm
NH3_OPT =     8;  NH3_S1 =    12;  NH3_S2 =    25;  NH3_S3 =     50   # ppm

# ── FAN-STUFEN ───────────────────────────────────────────────
FAN_STAGES = [
    (0,       20,  "#2C4560", "ECO — 20%"),
    (CO2_S1,  40,  GREEN,     "STUFE 1 — 40%"),
    (CO2_S2,  70,  ORANGE,    "STUFE 2 — 70%"),
    (CO2_S3, 100,  RED,       "ALARM — 100%"),
]

# ──────────────────────────────────────────

def img_b64(path):
    """Bild als base64-String laden (für inline HTML)"""
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


# ══════════════════════════════════════════════════════════════
# PDF BERICHT GENERATOR
# ══════════════════════════════════════════════════════════════
def generate_pdf_report(params: dict) -> bytes:
    """Erstellt einen druckbaren PDF-Simulationsbericht."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm)

    # ── Farben (Corporate Design °coolsulting)
    C_BLUE  = colors.HexColor("#36A9E1")
    C_DARK  = colors.HexColor("#3C3C3B")
    C_LIGHT = colors.HexColor("#F0F8FD")
    C_GREEN = colors.HexColor("#00C08B")
    C_ORANGE= colors.HexColor("#F5A623")
    C_RED   = colors.HexColor("#E63946")
    C_MUTED = colors.HexColor("#8899AA")
    C_WHITE = colors.white
    C_BLACK = colors.HexColor("#1A1A2E")

    # ── Styles
    def sty(name, **kw):
        defaults = dict(fontName="Helvetica", fontSize=9,
                        textColor=C_DARK, leading=13)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    S_TITLE   = sty("title",   fontSize=20, fontName="Helvetica-Bold",
                    textColor=C_BLUE, spaceAfter=2*mm, leading=24)
    S_SUBTITLE= sty("sub",     fontSize=10, textColor=C_MUTED, spaceAfter=4*mm)
    S_H1      = sty("h1",      fontSize=12, fontName="Helvetica-Bold",
                    textColor=C_BLUE, spaceBefore=4*mm, spaceAfter=2*mm)
    S_H2      = sty("h2",      fontSize=10, fontName="Helvetica-Bold",
                    textColor=C_DARK, spaceBefore=3*mm, spaceAfter=1*mm)
    S_BODY    = sty("body",    fontSize=9,  textColor=C_DARK, spaceAfter=1*mm)
    S_SMALL   = sty("small",   fontSize=7.5,textColor=C_MUTED)
    S_WARN    = sty("warn",    fontSize=9,  textColor=C_RED,  fontName="Helvetica-Bold")
    S_OK      = sty("ok",      fontSize=9,  textColor=C_GREEN,fontName="Helvetica-Bold")

    def tbl(data, col_widths, style_extra=None):
        base = [
            ('FONTNAME',    (0,0),(-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',    (0,0),(-1,-1), 8.5),
            ('BACKGROUND',  (0,0),(-1,0),  C_BLUE),
            ('TEXTCOLOR',   (0,0),(-1,0),  C_WHITE),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_LIGHT, C_WHITE]),
            ('GRID',        (0,0),(-1,-1), 0.3, C_MUTED),
            ('LEFTPADDING', (0,0),(-1,-1), 4),
            ('RIGHTPADDING',(0,0),(-1,-1), 4),
            ('TOPPADDING',  (0,0),(-1,-1), 3),
            ('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('VALIGN',      (0,0),(-1,-1), 'MIDDLE'),
        ]
        if style_extra:
            base += style_extra
        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle(base))
        return t

    p  = params
    now= datetime.now().strftime("%d.%m.%Y %H:%M")
    story = []

    # ── HEADER ────────────────────────────────────────────────
    story.append(Paragraph("BSF GAS-SIMULATOR", S_TITLE))
    story.append(Paragraph(
        f"Simulationsbericht &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"°coolsulting × REPLOID Group AG &nbsp;&nbsp;|&nbsp;&nbsp; LP 640_07 Rev.02 "
        f"&nbsp;&nbsp;|&nbsp;&nbsp; Erstellt: {now}", S_SUBTITLE))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_BLUE, spaceAfter=4*mm))

    # ── ZUSAMMENFASSUNG ────────────────────────────────────────
    story.append(Paragraph("1. Simulationsparameter", S_H1))

    data_params = [
        ["Parameter", "Zone 01", "Zone 02"],
        ["Raumvolumen [m³]",       f"{p['vol_z1']:.1f}",   f"{p['vol_z2']:.1f}"],
        ["Larvenmasse [t]",        f"{p['mass_z1']:.1f}",  f"{p['mass_z2']:.1f}"],
        ["Masttag",                f"Tag {p['mast_day']:.1f} ({p['h_now']:.0f}h)", "—"],
        ["Lüfter Volumenstrom",    f"{p['q1']:.0f} m³/h ({p['pct1']}%)",
                                   f"{p['q2']:.0f} m³/h"],
        ["Luftwechsel [ACH]",      f"{p['ach1']:.2f}",     f"{p['ach2']:.2f}"],
        ["CO<sub>2</sub> Emissionsrate",  f"{p['co2_rate']:.3f} g/kg/h (Ø)", "—"],
        ["NH<sub>3</sub> Emissionsrate",  f"{p['nh3_rate']:.5f} g/kg/h (Basis)", "—"],
    ]
    cw = [75*mm, 52*mm, 42*mm]
    story.append(tbl([[Paragraph(c, sty(f"tc{i}", fontSize=8.5,
                       textColor=C_WHITE if r==0 else C_DARK,
                       fontName="Helvetica-Bold" if r==0 else "Helvetica"))
                       for i,c in enumerate(row)]
                      for r,row in enumerate(data_params)], cw))
    story.append(Spacer(1, 4*mm))

    # ── ISTWERTE ──────────────────────────────────────────────
    story.append(Paragraph("2. Aktuelle Gaswerte (Masttag)", S_H1))

    def status_col(val, s1, s2, s3):
        if val >= s3: return C_RED
        if val >= s2: return C_ORANGE
        if val >= s1: return C_GREEN
        return C_DARK

    def status_txt(val, s1, s2, s3):
        if val >= s3: return "ALARM"
        if val >= s2: return "STUFE 2"
        if val >= s1: return "STUFE 1"
        return "ECO / OK"

    co2_col_z1 = status_col(p['co2_z1'], p['co2_s1'], p['co2_s2'], p['co2_s3'])
    nh3_col_z1 = status_col(p['nh3_z1'], p['nh3_s1'], p['nh3_s2'], p['nh3_s3'])
    co2_col_z2 = status_col(p['co2_z2'], p['co2_s1'], p['co2_s2'], p['co2_s3'])
    nh3_col_z2 = status_col(p['nh3_z2'], p['nh3_s1'], p['nh3_s2'], p['nh3_s3'])

    data_ist = [
        ["Gas", "Zone 01 [ppm]", "Status Z1", "Zone 02 [ppm]", "Status Z2"],
        [f"CO2",
         f"{p['co2_z1']:.0f}", status_txt(p['co2_z1'],p['co2_s1'],p['co2_s2'],p['co2_s3']),
         f"{p['co2_z2']:.0f}", status_txt(p['co2_z2'],p['co2_s1'],p['co2_s2'],p['co2_s3'])],
        [f"NH3",
         f"{p['nh3_z1']:.1f}", status_txt(p['nh3_z1'],p['nh3_s1'],p['nh3_s2'],p['nh3_s3']),
         f"{p['nh3_z2']:.1f}", status_txt(p['nh3_z2'],p['nh3_s1'],p['nh3_s2'],p['nh3_s3'])],
    ]
    style_ist = [
        ('TEXTCOLOR',(1,1),(1,1), co2_col_z1), ('FONTNAME',(1,1),(1,1),'Helvetica-Bold'),
        ('TEXTCOLOR',(2,1),(2,1), co2_col_z1), ('FONTNAME',(2,1),(2,1),'Helvetica-Bold'),
        ('TEXTCOLOR',(3,1),(3,1), co2_col_z2), ('FONTNAME',(3,1),(3,1),'Helvetica-Bold'),
        ('TEXTCOLOR',(4,1),(4,1), co2_col_z2), ('FONTNAME',(4,1),(4,1),'Helvetica-Bold'),
        ('TEXTCOLOR',(1,2),(1,2), nh3_col_z1), ('FONTNAME',(1,2),(1,2),'Helvetica-Bold'),
        ('TEXTCOLOR',(2,2),(2,2), nh3_col_z1), ('FONTNAME',(2,2),(2,2),'Helvetica-Bold'),
        ('TEXTCOLOR',(3,2),(3,2), nh3_col_z2), ('FONTNAME',(3,2),(3,2),'Helvetica-Bold'),
        ('TEXTCOLOR',(4,2),(4,2), nh3_col_z2), ('FONTNAME',(4,2),(4,2),'Helvetica-Bold'),
    ]
    story.append(tbl(data_ist, [35*mm,38*mm,38*mm,36*mm,22*mm], style_ist))
    story.append(Spacer(1, 4*mm))

    # ── SCHWELLENWERTE ────────────────────────────────────────
    story.append(Paragraph("3. Lüfterstufen & Schwellenwerte", S_H1))
    data_sw = [
        ["Stufe", "Lüfter [%]", "CO<sub>2</sub>-Schwelle [ppm]", "NH<sub>3</sub>-Schwelle [ppm]", "Farbe"],
        ["ECO",     f"{p['s_pct'][0]}%", f"< {p['s_co2'][1]:,}",  f"< {p['s_nh3'][1]}", "●"],
        ["STUFE 1", f"{p['s_pct'][1]}%", f"≥ {p['s_co2'][1]:,}",  f"≥ {p['s_nh3'][1]}", "●"],
        ["STUFE 2", f"{p['s_pct'][2]}%", f"≥ {p['s_co2'][2]:,}",  f"≥ {p['s_nh3'][2]}", "●"],
        ["ALARM",   f"{p['s_pct'][3]}%", f"≥ {p['s_co2'][3]:,}",  f"≥ {p['s_nh3'][3]}", "●"],
    ]
    dot_colors = [C_MUTED, C_GREEN, C_ORANGE, C_RED]
    style_sw = [(('TEXTCOLOR',(4,i+1),(4,i+1), dot_colors[i])) for i in range(4)]
    story.append(tbl(data_sw, [30*mm,28*mm,47*mm,47*mm,17*mm], style_sw))
    story.append(Spacer(1, 4*mm))

    # ── PHYSIK / METHODIK ─────────────────────────────────────
    story.append(Paragraph("4. Berechnungsgrundlagen", S_H1))
    story.append(Paragraph(
        "<b>Massenbilanz-Gleichgewicht (Steady-State):</b>", S_H2))
    story.append(Paragraph(
        "c [ppm] = c_Aussenluft + (Emissionsrate [m³/h] / Volumenstrom [m³/h]) × 10⁶", S_BODY))
    story.append(Paragraph(
        "<b>CO<sub>2</sub>-Kurvenform:</b> Glockenform (Sinus-Peak Tag 4), "
        f"Ø-Rate: {p['co2_rate']:.3f} g/kg/h, Peak ≈ {p['co2_rate']*3:.3f} g/kg/h "
        f"| Dichte CO<sub>2</sub>: 1.842 kg/m³", S_BODY))
    story.append(Paragraph(
        "<b>NH<sub>3</sub>-Kurvenform:</b> Exponentiell ab Tag 4, "
        f"Basis-Rate: {p['nh3_rate']:.5f} g/kg/h "
        f"| Dichte NH<sub>3</sub>: 0.769 kg/m³", S_BODY))
    story.append(Paragraph(
        "<b>Quellen:</b> Global 2000 (2024) — 1.414 g CO<sub>2</sub>/kg/8d; "
        "Chen et al. 2019 (Brill) — NH<sub>3</sub>-Exponentialanstieg; "
        "Engineering For Change — Mikroklima-Faktor 1.4–2.4×", S_SMALL))
    story.append(Spacer(1, 4*mm))

    # ── RAUMPARAMETER ─────────────────────────────────────────
    story.append(Paragraph("5. Anlagenparameter", S_H1))
    data_anlage = [
        ["Eigenschaft", "Zone 01", "Zone 02"],
        ["Abmessungen [m]",       "21.36 × 9.75 × 3.80",  "3.80 × 2.90 × 3.80"],
        ["Volumen [m³]",          f"{p['vol_z1']:.1f}",    f"{p['vol_z2']:.1f}"],
        ["Max. Volumenstrom",     f"{p['vol_z1']*6:.0f} m³/h (6 ACH)", "200 m³/h"],
        ["Substrat-Kapazität",    "201 Boxen × 258 kg",    "63 Boxen × 120 kg"],
        ["Max. Larvenmasse [kg]", "51.858",                 "7.560"],
        ["Projekt",               "REPLOID Group AG",       "LP 640_07 Rev.02"],
    ]
    story.append(tbl(data_anlage, [60*mm,57*mm,52*mm]))
    story.append(Spacer(1, 6*mm))

    # ── FOOTER ────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_MUTED, spaceAfter=2*mm))
    story.append(Paragraph(
        f"BSF Gas-Simulator v5.0 &nbsp;|&nbsp; °coolsulting GmbH &nbsp;|&nbsp; "
        f"Simulationsbericht automatisch erstellt am {now} &nbsp;|&nbsp; "
        "Alle Werte sind Simulationswerte — keine Messwerte.", S_SMALL))

    doc.build(story)
    buf.seek(0)
    return buf.read()

st.set_page_config(
    page_title="BSF Gas-Simulator v3.1 | coolsulting",
    page_icon="🦟",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;700&display=swap');

/* POE Vetica fallback stack: Barlow ist nächste verfügbare Alternative */
:root {{
    --font-body: 'Barlow', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    --font-mono: 'JetBrains Mono', 'Courier New', monospace;
}}

html, body, [class*="css"] {{
    background:{DARK}; color:{WHITE};
    font-family: var(--font-body);
    font-size: 16px;
}}
.stApp {{ background:{DARK}; }}
.main .block-container {{ padding:0.6rem 1.8rem 2rem 1.8rem; max-width:none; }}

/* ── Streamlit Topbar dunkel + Icons hellblau ── */
header[data-testid="stHeader"] {{
    background:{DARK} !important;
    border-bottom: 1px solid {BORDER} !important;
}}
header[data-testid="stHeader"] button {{
    color: {BLUE} !important;
}}
header[data-testid="stHeader"] svg {{
    fill: {BLUE} !important;
    color: {BLUE} !important;
}}
div[data-testid="stToolbar"] {{
    background:{DARK} !important;
}}
div[data-testid="stToolbar"] button {{
    color: {BLUE} !important;
}}
div[data-testid="stToolbar"] svg {{
    fill: {BLUE} !important;
}}
/* Hamburger + Deploy Buttons */
button[kind="header"] {{
    color: {BLUE} !important;
    background: transparent !important;
}}
.stDeployButton {{ display:none; }}

.topbar {{
    display:flex; justify-content:space-between; align-items:flex-end;
    padding-bottom:12px; border-bottom:1px solid {BORDER}; margin-bottom:18px;
}}
.tb-title {{
    font-family: var(--font-mono); font-size:1.05rem;
    color:{BLUE}; letter-spacing:3px; text-transform:uppercase; line-height:1.5;
    font-weight:700;
}}
.tb-meta {{ font-size:.8rem; color:{MUTED}; letter-spacing:1px; margin-top:5px; }}
.tb-right {{ text-align:right; font-family: var(--font-mono);
    font-size:.75rem; color:{MUTED}; letter-spacing:2px; line-height:1.9; }}

.sec {{
    font-family: var(--font-mono); font-size:.72rem; color:{BLUE};
    letter-spacing:3px; text-transform:uppercase;
    border-bottom:1px solid {BORDER}; padding-bottom:7px; margin-bottom:14px;
    font-weight:600;
}}
.sec.grn {{ color:{GREEN}; border-color:#0e2015; }}
.sec.ylw {{ color:{YELLOW}; border-color:#201800; }}
.sec.red {{ color:{RED}; border-color:#200810; }}

/* KPI Cards */
.kpi {{
    background:{CARD}; border:1px solid {BORDER}; border-top:3px solid {BLUE};
    border-radius:10px; padding:18px 18px; text-align:center; height:100%;
}}
.kpi.red {{ border-top-color:{RED};    background:#140810; }}
.kpi.ora {{ border-top-color:{ORANGE}; background:#130D04; }}
.kpi.grn {{ border-top-color:{GREEN};  background:#081408; }}
.kpi-lbl {{
    font-family: var(--font-mono); font-size:.68rem; color:{MUTED};
    letter-spacing:2px; text-transform:uppercase; margin-bottom:9px;
}}
.kpi-num {{
    font-family: var(--font-mono); font-size:2.6rem;
    font-weight:700; color:{BLUE}; line-height:1;
}}
.kpi-num.red {{ color:{RED}; }}
.kpi-num.ora {{ color:{ORANGE}; }}
.kpi-num.grn {{ color:{GREEN}; }}
.kpi-unit {{ font-size:.75rem; color:{MUTED}; margin-top:7px; letter-spacing:1px; }}

/* Breite Infokarte */
.infobox {{
    background:{CARD2}; border:1px solid {BORDER}; border-left:4px solid {BLUE};
    border-radius:10px; padding:20px 22px; font-size:1rem; line-height:1.9;
}}
.infobox h5 {{
    font-family: var(--font-mono); color:{BLUE}; font-size:.72rem;
    letter-spacing:2px; text-transform:uppercase; margin:0 0 12px 0; font-weight:600;
}}
.v {{ color:{GREEN}; font-family: var(--font-mono); font-size:1rem; }}
.lb {{ color:{MUTED}; font-size:.92rem; }}

/* Stufen-Pill */
.stage-pill {{
    border-radius:8px; padding:11px 14px; text-align:center;
    font-family: var(--font-mono); font-size:.72rem;
    font-weight:700; letter-spacing:2px; text-transform:uppercase;
    border:1px solid rgba(255,255,255,.04); margin-bottom:6px;
}}

.micro-badge {{
    background:#081A0F; border:1px solid #0e2a15; border-left:4px solid {GREEN};
    border-radius:9px; padding:14px 18px; font-family: var(--font-mono);
    font-size:.8rem; color:{GREEN}; letter-spacing:1px; line-height:1.8;
}}
.macro-badge {{
    background:#070A1A; border:1px solid #10182A; border-left:4px solid {BLUE};
    border-radius:9px; padding:14px 18px; font-family: var(--font-mono);
    font-size:.8rem; color:{BLUE}; letter-spacing:1px; line-height:1.8;
}}

section[data-testid="stSidebar"] {{ background:#050810; border-right:1px solid {BORDER}; }}
section[data-testid="stSidebar"] label {{ color:#4a6888 !important; font-size:.95rem; }}
section[data-testid="stSidebar"] p {{ color:#4a6888; font-size:.9rem; }}
hr {{ border-color:{BORDER}; margin:8px 0; }}
.foot {{ font-family: var(--font-mono); font-size:.62rem; color:#1C2C3C; letter-spacing:2px; }}
</style>
""", unsafe_allow_html=True)

# ── SESSION STATE ────────────────────────────────────────────
_def = dict(
    sim_active=False, sim_step=0, mast_day=1.0,
    flow_z1=30.0, flow_z2=25.0,
    hist_t=[0.0], hist_co2_z1=[420.0], hist_nh3_z1=[0.2],
    hist_co2_z2=[420.0], hist_nh3_z2=[0.2], hist_flow_z1=[30.0],
)
for k, v in _def.items():
    if k not in st.session_state: st.session_state[k] = v

# ── PHYSIK-ENGINE (korrekte Massenbilanz) ────────────────────
def co2_rate_g_kg_h(day, rate_avg=None):
    """CO2-Emissionsrate g/kg Substrat/h — Gauskurve, Peak Tag 4"""
    r = rate_avg if rate_avg is not None else CO2_RATE_AVG
    x = day / CO2_DAYS
    return r * (0.3 + 2.7 * np.sin(np.pi * x) ** 1.8)

def nh3_rate_g_kg_h(day, rate_base=None):
    """NH3-Emissionsrate g/kg Substrat/h — exponentiell ab Tag 4"""
    b = rate_base if rate_base is not None else NH3_RATE_BASE
    x = day / CO2_DAYS
    if x < 0.45:
        return b * (1.0 + 0.5 * x / 0.45)
    return b * 1.5 * np.exp(2.6 * (x - 0.45))

def calc_ppm(mass_kg, rate_g_kg_h, rho_gas, flow_pct, vol, ambient=CO2_AMBIENT):
    """
    Steady-State ppm-Berechnung (Massenbilanz Gleichgewicht)
    
    Emission:   E [m³/h] = mass_kg * rate [g/kg/h] / 1000 / rho_gas [kg/m³]
    Lüftung:    Q [m³/h] = fan_m3h(flow_pct, vol)
    Gleichgewicht: c_ss = c_aussen + (E/Q) * 1e6  [ppm]
    Bei geringer Lüftung: Konz. steigt → realistischer Anstieg
    """
    E_kg_h  = mass_kg * rate_g_kg_h / 1000.0    # kg Gas / h
    E_m3_h  = E_kg_h / rho_gas                   # m³ Gas / h
    Q_m3_h  = fan_m3h(flow_pct, vol)             # m³ Frischluft / h
    c_ss    = ambient + (E_m3_h / Q_m3_h) * 1e6  # ppm Gleichgewicht
    return round(c_ss, 1)

def macro_co2(mass_kg, flow_pct, vol, day, co2_r=None):
    r = co2_r if co2_r is not None else CO2_RATE_AVG
    return calc_ppm(mass_kg, co2_rate_g_kg_h(day, r), RHO_CO2, flow_pct, vol, CO2_AMBIENT)

def macro_nh3(mass_kg, flow_pct, vol, day, nh3_r=None):
    b = nh3_r if nh3_r is not None else NH3_RATE_BASE
    return calc_ppm(mass_kg, nh3_rate_g_kg_h(day, b), RHO_NH3, flow_pct, vol, 0.02)

def micro_factor(day):
    return 1.4 + 1.0 * ((day - 1) / (CO2_DAYS - 1))

def ach(flow_pct, vol):
    """Alias für ach_val — rückwärtskompatibel"""
    return ach_val(flow_pct, vol)

def autopilot_flow(co2, nh3, day, base_pct):
    """Autopilot: Lüfter-% basierend auf aktuellen Gaswerten"""
    if co2 > CO2_S3 or nh3 > NH3_S3: return 100.0
    if co2 > CO2_S2 or nh3 > NH3_S2: return 70.0
    if co2 > CO2_S1 or nh3 > NH3_S1: return 40.0
    return base_pct

def fan_stage(co2, nh3):
    if co2 > CO2_S3 or nh3 > NH3_S3: return 3, "ALARM — 100%",  RED,    100
    if co2 > CO2_S2 or nh3 > NH3_S2: return 2, "STUFE 2 — 70%", ORANGE,  70
    if co2 > CO2_S1 or nh3 > NH3_S1: return 1, "STUFE 1 — 40%", GREEN,   40
    return 0, "ECO — 20%", MUTED, 20

def get_stufe(co2, nh3):
    if co2 > CO2_S3 or nh3 > NH3_S3: return 3, "ALARM — EVAKUIERUNG", RED,    "red"
    if co2 > CO2_S2 or nh3 > NH3_S2: return 2, "WARNUNG opt/akust",   ORANGE, "ora"
    if co2 > CO2_S1 or nh3 > NH3_S1: return 1, "BETRIEB STUFE 1",     GREEN,  "grn"
    return 0, "STANDBY / ECO",                                          MUTED,  ""

# ── SIDEBAR ──────────────────────────────────────────────────
with st.sidebar:
    # coolsulting Logo prominent oben
    cool_b64 = img_b64("coolsulting_logo.png")
    if cool_b64:
        st.markdown(f"""<div style='padding:14px 8px 6px 8px;'>
<img src='data:image/png;base64,{cool_b64}' style='width:100%;display:block;'/></div>""",
            unsafe_allow_html=True)
    st.markdown(f"<div style='height:3px;background:linear-gradient(90deg,{BLUE},{GREEN});border-radius:2px;margin:6px 8px 10px;'></div>", unsafe_allow_html=True)

    rep_b64 = img_b64("reploid_logo.png")
    if rep_b64:
        st.markdown(f"""<div style='padding:0 50px 6px;'>
<img src='data:image/png;base64,{rep_b64}' style='width:100%;opacity:.8;'/></div>""",
            unsafe_allow_html=True)
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.58rem;color:{MUTED};letter-spacing:2px;text-align:center;padding-bottom:4px;'>HENKE / STEYERBERG — LP 640_07</p>", unsafe_allow_html=True)
    st.divider()

    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.72rem;color:{MUTED};letter-spacing:2px;font-weight:600;'>MASTPARAMETER</p>", unsafe_allow_html=True)
    mast_day = st.slider("Masttag (1–8)", 1.0, 8.0,
                          st.session_state.mast_day, 0.25,
                          help="Tag 1=Einlagern | Tag 8=Ernte. NH3 explodiert ab Tag 4!")
    mass_z1 = st.slider("Larvenmasse Zone 01 [t]", 5.0, 60.0, Z1_LARVEN_MAX/1000, 0.5)
    mass_z2 = st.slider("Larvenmasse Zone 02 [t]", 0.5, 10.0, Z2_LARVEN_MAX/1000, 0.2)

    st.divider()

    # ── LÜFTERSTUFEN — editierbar ──────────────────────────────
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.82rem;color:{WHITE};letter-spacing:2px;font-weight:700;margin-bottom:4px;'>LÜFTERSTUFEN — EDITIERBAR</p>", unsafe_allow_html=True)
    # Spalten-Header — deutlich sichtbar
    _hcols = st.columns([1.1, 1.1, 0.9])
    _hcols[0].markdown(f"<p style='font-family:JetBrains Mono;font-size:.78rem;color:{BLUE};font-weight:600;margin:0;'>CO₂ [ppm]</p>", unsafe_allow_html=True)
    _hcols[1].markdown(f"<p style='font-family:JetBrains Mono;font-size:.78rem;color:{ORANGE};font-weight:600;margin:0;'>NH₃ [ppm]</p>", unsafe_allow_html=True)
    _hcols[2].markdown(f"<p style='font-family:JetBrains Mono;font-size:.78rem;color:{YELLOW};font-weight:600;margin:0;'>Lüfter [%]</p>", unsafe_allow_html=True)

    # Stufen: (name, co2_default, nh3_default, pct_default, farbe)
    _stufen_def = [
        ("ECO",    420,   0, 20,  MUTED),
        ("STUFE 1", 3000, 12, 40, GREEN),
        ("STUFE 2", 5000, 25, 70, ORANGE),
        ("ALARM",  10000, 50,100, RED),
    ]
    stufen_co2 = []; stufen_nh3 = []; stufen_pct = []
    for i, (name, co2_d, nh3_d, pct_d, col) in enumerate(_stufen_def):
        st.markdown(f"<div style='font-family:JetBrains Mono;font-size:.78rem;color:{col};margin:6px 0 2px 0;font-weight:700;'>▶ {name}</div>", unsafe_allow_html=True)
        ca, cb, cc = st.columns([1.1, 1.1, 0.9])
        co2_v = ca.number_input(f"CO₂ ppm##{i}", 0, 20000, co2_d, 100, label_visibility="collapsed", key=f"s_co2_{i}")
        nh3_v = cb.number_input(f"NH₃ ppm##{i}", 0, 200,   nh3_d,   1, label_visibility="collapsed", key=f"s_nh3_{i}")
        pct_v = cc.number_input(f"Lüfter%##{i}", 0, 100,   pct_d,   5, label_visibility="collapsed", key=f"s_pct_{i}")
        stufen_co2.append(int(co2_v)); stufen_nh3.append(int(nh3_v)); stufen_pct.append(int(pct_v))

    # CO2_S1..S3 und NH3_S1..S3 aus editierbaren Stufen übernehmen
    CO2_S1, CO2_S2, CO2_S3 = stufen_co2[1], stufen_co2[2], stufen_co2[3]
    NH3_S1, NH3_S2, NH3_S3 = stufen_nh3[1], stufen_nh3[2], stufen_nh3[3]

    st.divider()
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.72rem;color:{MUTED};letter-spacing:2px;font-weight:600;'>LÜFTER MANUELL</p>", unsafe_allow_html=True)

    # Zone 01: Stufenwahl + absoluter m³/h Slider (0–20000)
    _slabels = [f"ECO — {stufen_pct[0]}%", f"STUFE 1 — {stufen_pct[1]}%",
                f"STUFE 2 — {stufen_pct[2]}%", f"ALARM — {stufen_pct[3]}%"]
    sz1_sel = st.radio("Stufe Zone 01", _slabels, index=0, key="sz1_radio")
    flow_z1_stufe = stufen_pct[_slabels.index(sz1_sel)]
    _z1_default = max(1, int(flow_z1_stufe / 100.0 * FAN_Z1_MAX_M3H))
    q1_manual = st.slider("Z1 [m³/h]", 0, 60000, _z1_default, 100, key="fz1_fine")
    flow_z1_manual = max(1, int(q1_manual / FAN_Z1_MAX_M3H * 100))
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.82rem;color:{BLUE};margin:2px 0 6px 0;'>"
                f"Z1: <b>{q1_manual} m³/h</b> → <b>{flow_z1_manual}%</b> ({q1_manual/VOL_Z1:.2f} ACH)</p>",
                unsafe_allow_html=True)
    st.session_state["fz1_pct_computed"] = flow_z1_manual
    st.session_state["fz1_m3h_computed"] = q1_manual

    # Zone 02: Radio-Stufen + Feinjustierung in m³/h (max 200 m³/h)
    st.markdown(f"<div style='font-family:JetBrains Mono;font-size:.72rem;color:{MUTED};margin:4px 0 2px 0;letter-spacing:1px;'>STUFE ZONE 02</div>", unsafe_allow_html=True)
    _slabels_z2 = [f"ECO — {stufen_pct[0]}%", f"STUFE 1 — {stufen_pct[1]}%",
                   f"STUFE 2 — {stufen_pct[2]}%", f"ALARM — {stufen_pct[3]}%"]
    sz2_sel = st.radio("Stufe Zone 02", _slabels_z2, index=0, key="sz2_radio")
    flow_z2_stufe_pct = stufen_pct[_slabels_z2.index(sz2_sel)]
    # Stufenwert in m³/h als Startwert
    _z2_default = min(60000, int(flow_z2_stufe_pct / 100.0 * FAN_Z2_MAX_M3H))
    # Absoluter Slider 0–200 m³/h, Stufe setzt den Defaultwert
    flow_z2_m3h = st.slider("Z2 [m³/h]", 0, 60000, min(60000,_z2_default), 100, key="fz2_fine")
    flow_z2_manual    = max(1, int(flow_z2_m3h / FAN_Z2_MAX_M3H * 100))
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.82rem;color:{GREEN};margin:2px 0 6px 0;'>"
                f"Z2: <b>{flow_z2_m3h} m³/h</b> &nbsp;|&nbsp; <b>{flow_z2_manual}%</b> &nbsp;|&nbsp; {ach_val(flow_z2_manual,VOL_Z2):.2f} ACH</p>",
                unsafe_allow_html=True)
    st.session_state["fz2_m3h_computed"] = flow_z2_m3h

    st.divider()
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.72rem;color:{MUTED};letter-spacing:2px;font-weight:600;'>EMISSIONSRATEN — EDITIERBAR</p>", unsafe_allow_html=True)
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.62rem;color:{MUTED};'>Quelle: Global 2000 (2024) | Chen et al. (2019)</p>", unsafe_allow_html=True)

    ea, eb = st.columns(2)
    CO2_RATE_AVG  = ea.number_input("CO₂ Ø g/kg/h", 0.01, 2.0,  0.125, 0.005,
        format="%.3f", help="Durchschnittliche CO2-Emissionsrate g/kg Substrat/h (Glockenform, Peak ≈ 3× Ø)")
    NH3_RATE_BASE = eb.number_input("NH₃ Basis g/kg/h", 0.0001, 0.01, 0.001, 0.0001,
        format="%.5f", help="NH3-Basisrate Tag 1 — steigt exponentiell bis ca. 45× bis Tag 8")

    # Anzeige der resultierenden Peak-Werte
    co2_peak_val = CO2_RATE_AVG * 3.0   # ca. Faktor 3 durch Sinus-Kurve
    nh3_peak_val = NH3_RATE_BASE * 1.5 * __import__("math").exp(2.6 * (1.0 - 0.45))
    st.markdown(f"""
<div style='font-family:JetBrains Mono;font-size:.72rem;line-height:1.9;margin:4px 0;'>
<span style='color:{BLUE};'>CO₂ Peak (Tag 4): ~{co2_peak_val:.3f} g/kg/h</span><br>
<span style='color:{ORANGE};'>NH₃ Peak (Tag 8): ~{nh3_peak_val*1000:.3f} mg/kg/h</span>
</div>""", unsafe_allow_html=True)
    # Werte in session_state — damit Physik-Aufrufe außerhalb Sidebar sie kennen
    st.session_state["co2_rate_avg"] = float(CO2_RATE_AVG)
    st.session_state["nh3_rate_base"] = float(NH3_RATE_BASE)

    st.divider()
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.72rem;color:{MUTED};letter-spacing:2px;font-weight:600;'>AUTOPILOT</p>", unsafe_allow_html=True)
    sa, sb, sc = st.columns(3)
    if sa.button("▶ START", use_container_width=True):
        st.session_state.update(dict(
            sim_active=True, sim_step=0, mast_day=1.0,
            flow_z1=30.0, flow_z2=25.0,
            hist_t=[0.0], hist_co2_z1=[420.0], hist_nh3_z1=[0.2],
            hist_co2_z2=[420.0], hist_nh3_z2=[0.2], hist_flow_z1=[30.0],
        ))
    if sb.button("⏹ STOP", use_container_width=True):
        st.session_state.sim_active = False
    if sc.button("↺ RESET", use_container_width=True):
        for k, v in _def.items(): st.session_state[k] = v
        st.rerun()

    if st.session_state.sim_active:
        d = st.session_state.mast_day
        fz1_now = int(st.session_state.flow_z1)
        fz2_now = int(st.session_state.flow_z2)
        # Progress zeigt Lüfterstärke, nicht Masttag
        st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.72rem;color:{MUTED};margin:6px 0 2px 0;'>Masttag {d:.1f}/8</p>", unsafe_allow_html=True)
        st.progress(min(1.0, fz1_now/100.0), text=f"Z1: {fan_m3h(fz1_now,VOL_Z1,FAN_Z1_MAX_M3H):.0f} m³/h ({fz1_now}%)")
        st.progress(min(1.0, fz2_now/100.0), text=f"Z2: {fan_m3h_z2(fz2_now):.0f} m³/h ({fz2_now}%)")
        st.markdown(f"""
<div style='font-family:JetBrains Mono;font-size:.78rem;margin:6px 0;line-height:1.8;'>
<span style='color:{BLUE};'>▶ Z1: {fz1_now}% &nbsp; {ach(fz1_now,VOL_Z1):.2f} ACH</span><br>
<span style='color:{GREEN};'>▶ Z2: {fz2_now}% &nbsp; {ach(fz2_now,VOL_Z2):.2f} ACH</span>
</div>""", unsafe_allow_html=True)

# Emissionsraten aus Sidebar (editierbar)
CO2_RATE_AVG  = st.session_state.get("co2_rate_avg",  0.125)
NH3_RATE_BASE = st.session_state.get("nh3_rate_base", 0.001)   # g/kg/h = 1 mg/kg/h — realistischer BSF-Default

# PDF-Button — nach Emissionsraten damit Werte verfügbar
with st.sidebar:
    st.divider()
    st.markdown(f"<p style='font-family:JetBrains Mono;font-size:.72rem;color:{MUTED};letter-spacing:2px;font-weight:600;'>PDF BERICHT</p>", unsafe_allow_html=True)
    # Button-Farbe: hellblau mit dunkelgrauer Schrift
    st.markdown(f"""<style>
div[data-testid="stSidebar"] div.stButton > button[kind="primary"] {{
    background-color: {BLUE} !important;
    color: #1A2535 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 700 !important;
    border: none !important;
}}
div[data-testid="stSidebar"] div.stButton > button[kind="primary"]:hover {{
    background-color: #5BBFE8 !important;
    color: #07090E !important;
}}
</style>""", unsafe_allow_html=True)
    if st.button("📄 BERICHT GENERIEREN", use_container_width=True, type="primary"):
        with st.spinner("Generiere PDF..."):
            # flow_z1/z2 aus session_state (werden weiter unten gesetzt, Fallback auf Defaults)
            _flow_z1     = st.session_state.get("fz1_pct_computed", 20)
            _q1_m3h      = st.session_state.get("fz1_m3h_computed", int(0.2 * FAN_Z1_MAX_M3H))
            _flow_z2_m3h = st.session_state.get("fz2_m3h_computed", int(0.2 * FAN_Z2_MAX_M3H))
            _flow_z2     = max(1, int(_flow_z2_m3h / FAN_Z2_MAX_M3H * 100))
            _co2_z1 = macro_co2(mass_z1*1000, _flow_z1, VOL_Z1, mast_day)
            _nh3_z1 = macro_nh3(mass_z1*1000, _flow_z1, VOL_Z1, mast_day)
            _co2_z2 = macro_co2(mass_z2*1000, _flow_z2, VOL_Z2, mast_day)
            _nh3_z2 = macro_nh3(mass_z2*1000, _flow_z2, VOL_Z2, mast_day)
            _q1 = _q1_m3h
            _q2 = _flow_z2_m3h
            _stufen_co2 = [st.session_state.get(f"s_co2_{i}", d) for i,d in enumerate([420,3000,5000,10000])]
            _stufen_nh3 = [st.session_state.get(f"s_nh3_{i}", d) for i,d in enumerate([0,12,25,50])]
            _stufen_pct = [st.session_state.get(f"s_pct_{i}", d) for i,d in enumerate([20,40,70,100])]
            pdf_params = dict(
                date      = datetime.now().strftime("%d.%m.%Y %H:%M"),
                mast_day  = mast_day,
                mass_z1   = mass_z1, mass_z2   = mass_z2,
                mass_z1_kg= mass_z1*1000, mass_z2_kg= mass_z2*1000,
                vol_z1    = VOL_Z1,   vol_z2    = VOL_Z2,
                z1_l=Z1_L, z1_b=Z1_B, z1_h=Z1_H,
                z2_l=Z2_L, z2_b=Z2_B, z2_h=Z2_H,
                flow_z1   = _flow_z1,  flow_z2  = _flow_z2,
                q1=_q1, q2=_q2,
                ach_z1    = _q1/max(VOL_Z1,1), ach_z2 = max(_flow_z2_m3h,1)/VOL_Z2,
                fan_z1_max= FAN_Z1_MAX_M3H, fan_z2_max= FAN_Z2_MAX_M3H,
                boxes_z1  = 201, box_kg_z1 = 258,
                boxes_z2  = 63,  box_kg_z2 = 120,
                co2_z1=_co2_z1, nh3_z1=_nh3_z1,
                co2_z2=_co2_z2, nh3_z2=_nh3_z2,
                co2_s1=CO2_S1, co2_s2=CO2_S2, co2_s3=CO2_S3,
                nh3_s1=NH3_S1, nh3_s2=NH3_S2, nh3_s3=NH3_S3,
                co2_rate  = CO2_RATE_AVG,
                nh3_rate  = NH3_RATE_BASE,
                stufen    = dict(co2=_stufen_co2, nh3=_stufen_nh3, pct=_stufen_pct),
            )
            try:
                pdf_bytes = make_pdf_report(pdf_params)
                fname = f"BSF_Bericht_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                st.download_button(
                    label="⬇ PDF HERUNTERLADEN",
                    data=pdf_bytes,
                    file_name=fname,
                    mime="application/pdf",
                    use_container_width=True,
                )
                st.success("Bericht bereit!")
            except ImportError as e:
                st.error("📦 reportlab fehlt!")
                st.code("pip install reportlab", language="bash")
                st.info("Bitte obigen Befehl im Terminal ausführen, dann Streamlit neu starten.")
            except Exception as e:
                st.error(f"PDF Fehler: {e}")
                import traceback; st.code(traceback.format_exc())

# ── SIMULATION ───────────────────────────────────────────────
if st.session_state.sim_active:
    st.session_state.sim_step += 1
    step = st.session_state.sim_step
    st.session_state.mast_day = min(8.0, 1.0 + step * (7.0 / 120.0))
    mast_day = st.session_state.mast_day

    flow_z1 = autopilot_flow(
        macro_co2(mass_z1*1000, 0, VOL_Z1, mast_day),
        macro_nh3(mass_z1*1000, 0, VOL_Z1, mast_day), mast_day, 28.0)
    flow_z2 = autopilot_flow(
        macro_co2(mass_z2*1000, 0, VOL_Z2, mast_day),
        macro_nh3(mass_z2*1000, 0, VOL_Z2, mast_day), mast_day, 22.0)
    st.session_state.flow_z1 = flow_z1
    st.session_state.flow_z2 = flow_z2

    co2_z1 = macro_co2(mass_z1*1000, flow_z1, VOL_Z1, mast_day)
    nh3_z1 = macro_nh3(mass_z1*1000, flow_z1, VOL_Z1, mast_day)
    co2_z2 = macro_co2(mass_z2*1000, flow_z2, VOL_Z2, mast_day)
    nh3_z2 = macro_nh3(mass_z2*1000, flow_z2, VOL_Z2, mast_day)

    t_val = (step * 0.25) / 60.0
    for lst, val in [("hist_t", t_val), ("hist_co2_z1", co2_z1),
                     ("hist_nh3_z1", nh3_z1), ("hist_co2_z2", co2_z2),
                     ("hist_nh3_z2", nh3_z2), ("hist_flow_z1", flow_z1)]:
        st.session_state[lst].append(val)
        if len(st.session_state[lst]) > 200:
            st.session_state[lst] = st.session_state[lst][-200:]
else:
    mast_day = mast_day  # vom Slider
    flow_z1 = flow_z1_manual   # % — m³/h = q1_manual
    flow_z2 = flow_z2_manual
    co2_z1 = macro_co2(mass_z1*1000, flow_z1, VOL_Z1, mast_day)
    nh3_z1 = macro_nh3(mass_z1*1000, flow_z1, VOL_Z1, mast_day)
    co2_z2 = macro_co2(mass_z2*1000, flow_z2, VOL_Z2, mast_day)
    nh3_z2 = macro_nh3(mass_z2*1000, flow_z2, VOL_Z2, mast_day)
    # Manueller Modus: History mit aktuellem Wert befüllen (für Echtzeit-Charts)
    t_val = len(st.session_state.hist_t) * 0.25 / 60.0
    for lst, val in [("hist_t", t_val), ("hist_co2_z1", co2_z1),
                     ("hist_nh3_z1", nh3_z1), ("hist_co2_z2", co2_z2),
                     ("hist_nh3_z2", nh3_z2), ("hist_flow_z1", flow_z1)]:
        st.session_state[lst].append(val)
        if len(st.session_state[lst]) > 200:
            st.session_state[lst] = st.session_state[lst][-200:]

mf = micro_factor(mast_day)
co2_micro = co2_z1 * mf
nh3_micro = nh3_z1 * mf
s1, t1, c1, cl1 = get_stufe(co2_z1, nh3_z1)
s2, t2, c2, cl2 = get_stufe(co2_z2, nh3_z2)
fs_nr, fs_txt, fs_col, fs_pct = fan_stage(co2_z1, nh3_z1)

# ── TOPBAR ───────────────────────────────────────────────────
st.markdown(f"""
<div class='topbar'>
  <div>
    <div class='tb-title'>BSF Kühllager Gas-Simulator</div>
    <div class='tb-meta'>
      Henke / Steyerberg &nbsp;|&nbsp; LP 640_07 Rev.02 &nbsp;|&nbsp;
      REPLOID Group AG &nbsp;&times;&nbsp; coolsulting &nbsp;|&nbsp; v3.1
    </div>
  </div>
  <div class='tb-right'>
    {datetime.now().strftime('%d.%m.%Y  %H:%M:%S')}<br>
    Masttag: <span style='color:{YELLOW};'>{mast_day:.1f}/8</span> &nbsp;&nbsp;
    CO2-Rate: <span style='color:{ORANGE};'>{co2_rate_g_kg_h(mast_day):.1f} g/kg/h</span> &nbsp;&nbsp;
    NH3-Rate: <span style='color:{RED};'>{nh3_rate_g_kg_h(mast_day)*1000:.0f} mg/kg/h</span> &nbsp;&nbsp;
    Luefter-Stufe: <span style='color:{fs_col};'>{fs_txt}</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── BESCHREIBUNG (aufklappbar) ────────────────────────────────
with st.expander("ℹ️  Über diese Simulation — Funktionsweise & Bedienung", expanded=False):
    st.markdown(f"""
<div style='font-family:Barlow,Helvetica,sans-serif;font-size:1rem;line-height:1.9;color:{WHITE};padding:4px 0;'>

<p style='font-family:JetBrains Mono;font-size:.75rem;color:{BLUE};letter-spacing:3px;text-transform:uppercase;margin-bottom:14px;font-weight:600;'>
BSF KÜHLLAGER GAS-SIMULATOR — REPLOID GROUP AG × COOLSULTING</p>

<p>Diese interaktive Simulation visualisiert die <strong style='color:{BLUE};'>Gaskonzentrationen CO₂ und NH₃</strong> 
in einem BSF-Larvenkühllager (Schwarze Soldatenfliege / <em>Hermetia illucens</em>) über den gesamten 8-tägigen 
Mastzyklus — basierend auf wissenschaftlichen Emissionsdaten.</p>

<p style='margin-top:12px;font-family:JetBrains Mono;font-size:.68rem;color:{GREEN};letter-spacing:2px;'>WISSENSCHAFTLICHE BASIS</p>
<ul style='margin:6px 0 12px 20px;'>
  <li><strong style='color:{BLUE};'>CO₂:</strong> 1.414 g/kg Biomasse über 8 Masttage (Global 2000 Abschlussbericht EIP-Projekt Larvenzucht)</li>
  <li><strong style='color:{ORANGE};'>NH₃:</strong> Exponentieller Anstieg ab Tag 4 — bis zu 15× höher als am Einlagertag (Chen et al. 2019, Brill 2024)</li>
  <li><strong style='color:{GREEN};'>Mikroklima:</strong> Direkt über dem Larvenbett ist die Konzentration 1,4× bis 2,4× höher als im Raumschnitt (Engineering For Change)</li>
</ul>

<p style='margin-top:12px;font-family:JetBrains Mono;font-size:.68rem;color:{BLUE};letter-spacing:2px;'>RAUMZONEN (LP 640_07 Rev.02)</p>
<ul style='margin:6px 0 12px 20px;'>
  <li><strong>Zone 01 — Mastlarven:</strong> 21,36 × 9,75 × 3,80 m (≈ 790 m³) — max. 10 °C — 201 Palettenboxen à 258 kg = 51,9 t</li>
  <li><strong>Zone 02 — Junglarven:</strong> 3,80 × 2,90 × 3,80 m (≈ 43 m³) — max. 13 °C — 63 Holzboxen à 120 kg = 7,6 t</li>
</ul>

<p style='margin-top:12px;font-family:JetBrains Mono;font-size:.68rem;color:{YELLOW};letter-spacing:2px;'>LÜFTUNGSKONZEPT</p>
<ul style='margin:6px 0 12px 20px;'>
  <li><strong style='color:{BLUE};'>CO₂ (ρ = 1,84 kg/m³, schwerer als Luft):</strong> Absaugung bodennah hinten rechts</li>
  <li><strong style='color:{YELLOW};'>NH₃ (ρ = 0,77 kg/m³, leichter als Luft):</strong> Absaugung deckennah hinten rechts</li>
  <li><strong style='color:{GREEN};'>Diagonalströmung:</strong> Frischluft vorne links oben + unten — verhindert Totzonen</li>
  <li>Chemischer/Biologischer Abluft-Wäscher reduziert NH₃-Emissionen um bis zu 82 %</li>
</ul>

<p style='margin-top:12px;font-family:JetBrains Mono;font-size:.68rem;color:{RED};letter-spacing:2px;'>GRENZWERTE</p>
<table style='font-size:.9rem;border-collapse:collapse;margin:6px 0 12px 0;'>
  <tr style='color:{MUTED};font-family:JetBrains Mono;font-size:.68rem;'>
    <td style='padding:3px 20px 3px 0;'>Stufe</td>
    <td style='padding:3px 20px 3px 0;'>CO₂</td>
    <td style='padding:3px 20px 3px 0;'>NH₃</td>
    <td style='padding:3px 0;'>Maßnahme</td>
  </tr>
  <tr style='color:{GREEN};'><td style='padding:3px 20px 3px 0;font-family:JetBrains Mono;'>S0 Optimal</td><td>&lt; 1.000 ppm</td><td>&lt; 8 ppm</td><td>Standby / ECO</td></tr>
  <tr style='color:{GREEN};'><td style='padding:3px 20px 3px 0;font-family:JetBrains Mono;'>S1 Betrieb</td><td>&gt; 3.000 ppm</td><td>&gt; 12 ppm</td><td>Lüfter Stufe 1 — 40%</td></tr>
  <tr style='color:{ORANGE};'><td style='padding:3px 20px 3px 0;font-family:JetBrains Mono;'>S2 Warnung</td><td>&gt; 5.000 ppm</td><td>&gt; 25 ppm</td><td>Lüfter Stufe 2 — 70% + opt. Alarm</td></tr>
  <tr style='color:{RED};'><td style='padding:3px 20px 3px 0;font-family:JetBrains Mono;'>S3 Alarm</td><td>&gt; 10.000 ppm</td><td>&gt; 50 ppm</td><td>100% + Evakuierung</td></tr>
</table>

<p style='margin-top:12px;font-family:JetBrains Mono;font-size:.68rem;color:{MUTED};letter-spacing:2px;'>BEDIENUNG</p>
<ul style='margin:6px 0 0 20px;color:{MUTED};'>
  <li><strong style='color:{WHITE};'>Manuell:</strong> Masttag-Slider bewegen → Gaskonzentration ändert sich live</li>
  <li><strong style='color:{WHITE};'>Autopilot START:</strong> Simuliert den kompletten 8-Tage-Zyklus — Lüftung regelt automatisch</li>
  <li><strong style='color:{WHITE};'>3D-Ansicht:</strong> Zeigt CO₂-Bodenschicht (rot) und NH₃-Deckenakkumulation (gelb) + Strömungsvektoren</li>
</ul>
</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════
# BLOCK 1 — KPI ZONE 01 (4 Spalten)
# ════════════════════════════════════════════════
st.markdown("<div class='sec'>Zone 01 — Mastlarven — Makroklima (Raumluft) — max. 10 °C — 201 Boxen à 258 kg</div>", unsafe_allow_html=True)

def kpi_html(lbl, val, unit, cls=""):
    return f"""<div class='kpi {cls}'>
  <div class='kpi-lbl'>{lbl}</div>
  <div class='kpi-num {cls}'>{val}</div>
  <div class='kpi-unit'>{unit}</div>
</div>"""

co2c = "red" if co2_z1>CO2_S3 else "ora" if co2_z1>CO2_S2 else "grn" if co2_z1<CO2_S1 else ""
nh3c = "red" if nh3_z1>NH3_S3 else "ora" if nh3_z1>NH3_S2 else "grn" if nh3_z1<NH3_S1 else ""

ka, kb, kc, kd = st.columns(4)
ka.markdown(kpi_html("CO2 Makroklima", f"{int(co2_z1):,}", "ppm", co2c), unsafe_allow_html=True)
kb.markdown(kpi_html("NH3 Makroklima", f"{nh3_z1:.1f}", "ppm", nh3c), unsafe_allow_html=True)
kc.markdown(kpi_html("Luefter Z1", f"{int(flow_z1)}", "%"), unsafe_allow_html=True)
kd.markdown(f"""<div class='kpi' style='border-top-color:{c1};'>
  <div class='kpi-lbl'>Status Zone 01</div>
  <div style='font-family:JetBrains Mono;font-size:.78rem;font-weight:700;color:{c1};margin:8px 0 5px;line-height:1.4;'>{t1}</div>
  <div class='kpi-unit'>ACH: {ach(flow_z1,VOL_Z1):.1f} /h &nbsp;|&nbsp; Vol: {VOL_Z1:.0f} m³</div>
</div>""", unsafe_allow_html=True)

# MIKROKLIMA
st.markdown("<div class='sec grn' style='margin-top:10px;'>Mikroklima — direkt über Larvenbett (CO2 schwerer: sammelt sich über Wannen)</div>", unsafe_allow_html=True)
ma, mb, mc, md = st.columns(4)
co2mc = "red" if co2_micro>CO2_S3 else "ora" if co2_micro>CO2_S2 else ""
nh3mc = "red" if nh3_micro>NH3_S3 else "ora" if nh3_micro>NH3_S2 else ""
ma.markdown(kpi_html("CO2 Mikroklima", f"{int(co2_micro):,}", "ppm am Bett", co2mc), unsafe_allow_html=True)
mb.markdown(kpi_html("NH3 Mikroklima", f"{nh3_micro:.1f}", "ppm am Bett", nh3mc), unsafe_allow_html=True)
mc.markdown(f"""<div class='micro-badge'>
MIKRO / MAKRO FAKTOR<br>
<span style='font-size:1.6rem;color:{GREEN};font-family:JetBrains Mono;font-weight:700;'>{mf:.2f}×</span><br>
<span style='font-size:.62rem;color:{MUTED};'>steigt von 1.4× (Tag 1) → 2.4× (Tag 8)</span>
</div>""", unsafe_allow_html=True)
md.markdown(f"""<div class='macro-badge'>
BED VENTILATION<br>
<span style='font-size:.85rem;'>Direktabsaugung über Wannen</span><br>
<span style='font-size:.62rem;color:{MUTED};'>Reduktion Mikroklima: −40 bis −60%<br>
Engineering For Change (Sanergy)</span>
</div>""", unsafe_allow_html=True)

# ZONE 02
st.markdown("<div class='sec grn' style='margin-top:10px;'>Zone 02 — Junglarven — max. 13 °C — 63 Holzboxen à 120 kg</div>", unsafe_allow_html=True)
ja, jb, jc, jd = st.columns(4)
co2c2 = "red" if co2_z2>CO2_S3 else "ora" if co2_z2>CO2_S2 else ""
nh3c2 = "red" if nh3_z2>NH3_S3 else "ora" if nh3_z2>NH3_S2 else ""
ja.markdown(kpi_html("CO2 Zone 02", f"{int(co2_z2):,}", "ppm", co2c2), unsafe_allow_html=True)
jb.markdown(kpi_html("NH3 Zone 02", f"{nh3_z2:.1f}", "ppm", nh3c2), unsafe_allow_html=True)
jc.markdown(kpi_html("Luefter Z2", f"{int(flow_z2)}", "%"), unsafe_allow_html=True)
jd.markdown(f"""<div class='kpi' style='border-top-color:{c2};'>
  <div class='kpi-lbl'>Status Zone 02</div>
  <div style='font-family:JetBrains Mono;font-size:.78rem;font-weight:700;color:{c2};margin:8px 0 5px;'>{t2}</div>
  <div class='kpi-unit'>ACH: {ach(flow_z2,VOL_Z2):.1f} /h &nbsp;|&nbsp; Vol: {VOL_Z2:.0f} m³</div>
</div>""", unsafe_allow_html=True)

st.divider()

# ════════════════════════════════════════════════
# BLOCK 2 — 3D VISUALISIERUNG (volle Breite, unten)
# ════════════════════════════════════════════════

# ── DIAGRAMME LINKS + SCHALTSTUFEN/INFO RECHTS ──
# Diagramme volle Breite
if True:
    days = np.linspace(1, 8, 100)
    ht   = st.session_state.hist_t       or [0, 0.5]
    hc1  = st.session_state.hist_co2_z1  or [co2_z1]*2
    hn1  = st.session_state.hist_nh3_z1  or [nh3_z1]*2
    hc2  = st.session_state.hist_co2_z2  or [co2_z2]*2
    hn2  = st.session_state.hist_nh3_z2  or [nh3_z2]*2
    hfl  = st.session_state.hist_flow_z1 or [flow_z1]*2

    CHART_H   = 420
    FONT_SIZE = 14

    # Dynamische Kurven: CO2/NH3 ppm über alle 8 Tage
    # bei aktueller Larvenmasse UND aktueller Lüfterleistung
    co2_ppm_arr  = [macro_co2(mass_z1*1000, flow_z1, VOL_Z1, d) for d in days]
    nh3_ppm_arr  = [macro_nh3(mass_z1*1000, flow_z1, VOL_Z1, d) for d in days]
    # Zusätzlich: bei 100% Lüfter als Referenz (Minimum)
    co2_100_arr  = [macro_co2(mass_z1*1000, 100,     VOL_Z1, d) for d in days]
    nh3_100_arr  = [macro_nh3(mass_z1*1000, 100,     VOL_Z1, d) for d in days]
    # Bei 20% ECO (Maximum / Worst Case)
    co2_20_arr   = [macro_co2(mass_z1*1000, 20,      VOL_Z1, d) for d in days]
    nh3_20_arr   = [macro_nh3(mass_z1*1000, 20,      VOL_Z1, d) for d in days]

    q_now = fan_m3h(flow_z1, VOL_Z1)

    # ════════════════════════════════════════════════
    # DIAGRAMME — sauber, 4 Stück, klar strukturiert
    # ════════════════════════════════════════════════
    # X-Achse: Stunden 0–96 (= 4 Tage Mastdauer sichtbar)
    hours = np.linspace(0, 288, 400)         # 0..288 h = 12 Tage
    days  = 1.0 + hours / 24.0              # Masttag für Physik-Funktionen (0..288h)
    h_now = (mast_day - 1.0) * 24.0         # aktueller Masttag → Stunden

    CH   = 400   # Chart-Höhe CO2 px
    CH_NH3 = 800  # Chart-Höhe NH3 px (doppelt)
    FS   = 13    # Font-Size

    def base_layout(y_range=None, title_y2=None, nh3=False, log=False):
        lo = dict(
            height=CH_NH3 if nh3 else CH, paper_bgcolor=DARK, plot_bgcolor=DARK,
            font=dict(color=WHITE, size=FS),
            xaxis=dict(title="Stunden [h]", color=WHITE, gridcolor=BORDER,
                       tickmode='linear', dtick=24,
                       range=[0, 288],
                       tickfont=dict(size=FS), title_font=dict(size=FS, color=WHITE),
                       # Tag-Markierungen als vertikale Hilfslinien
                       ),
            yaxis=dict(title="ppm", color=WHITE, gridcolor=BORDER,
                       tickfont=dict(size=FS), title_font=dict(size=FS, color=WHITE),
                       range=y_range, type='log' if log else 'linear'),
            legend=dict(font=dict(size=12, color=WHITE), bgcolor='rgba(0,0,0,0)',
                        x=0.01, y=0.99, xanchor='left', yanchor='top'),
            margin=dict(l=60, r=90, t=20, b=50),
        )
        if title_y2:
            lo['yaxis2'] = dict(
                title=title_y2, overlaying='y', side='right',
                color=YELLOW, tickfont=dict(size=12),
                title_font=dict(size=12, color=YELLOW),
                range=[0, 120], showgrid=False,
            )
        return lo

    def add_day_markers(fig, ymax):
        """Tag 1–12 als vertikale Markierungen alle 24h"""
        for d in range(1, 13):
            h = (d-1)*24
            fig.add_vline(x=h, line_color=BORDER, line_dash="dot", line_width=1)
            fig.add_annotation(x=h+1, y=ymax*0.97, text=f"T{d}", showarrow=False,
                font=dict(color=MUTED, size=10, family="JetBrains Mono"), xanchor="left")

    def vline_now(fig, x_h, y, label, color):
        fig.add_vline(x=x_h, line_color=YELLOW, line_dash="dash", line_width=2)
        fig.add_annotation(x=x_h, y=y, text=f" {x_h:.0f}h: {label}",
            showarrow=False, font=dict(color=color, size=12, family="JetBrains Mono"),
            xanchor="left", bgcolor="rgba(0,0,0,0.5)")

    # ─────────────────────────────────────────────────
    # CHART 1 — CO2 Zone 01
    # ─────────────────────────────────────────────────
    c1_ist  = macro_co2(mass_z1*1000, flow_z1, VOL_Z1, mast_day)
    c1_soll = CO2_S1   # Zielwert = S1
    c1_arr  = [macro_co2(mass_z1*1000, flow_z1, VOL_Z1, d) for d in days]
    fl_arr  = [autopilot_flow(macro_co2(mass_z1*1000,flow_z1,VOL_Z1,d),
                              macro_nh3(mass_z1*1000,flow_z1,VOL_Z1,d), d, 20)
               for d in days]

    st.markdown(
        f"<div class='sec'>Zone 01 — CO₂ &nbsp;|&nbsp; IST: <b style='color:{BLUE};'>{c1_ist:.0f} ppm</b>"
        f" &nbsp;|&nbsp; Lüfter: <b style='color:{YELLOW};'>{fan_m3h(flow_z1,VOL_Z1):.0f} m³/h</b></div>",
        unsafe_allow_html=True)

    # Treppenkurve: welche Lüfterstufe wird bei welchem CO2-Wert aktiv?
    # Stufe schaltet wenn CO2-Kurve die Schwelle überschreitet
    fan_step_arr = []
    for co2_val in c1_arr:
        if   co2_val >= stufen_co2[3]: fan_step_arr.append(stufen_pct[3])
        elif co2_val >= stufen_co2[2]: fan_step_arr.append(stufen_pct[2])
        elif co2_val >= stufen_co2[1]: fan_step_arr.append(stufen_pct[1])
        else:                          fan_step_arr.append(stufen_pct[0])

    fig1 = go.Figure()
    # Schwellenwerte CO2 mit ppm-Beschriftung
    for y, col, lbl in [(CO2_S1,GREEN,f"{CO2_S1:,} ppm"),(CO2_S2,ORANGE,f"{CO2_S2:,} ppm"),(CO2_S3,RED,f"{CO2_S3:,} ppm")]:
        fig1.add_hline(y=y, line_color=col, line_dash="dash", line_width=1.5,
            annotation_text=lbl, annotation_font=dict(color=col, size=12),
            annotation_position="right")
    # Errechnete CO2-Kurve
    fig1.add_trace(go.Scatter(x=hours, y=c1_arr,
        name=f"CO₂ IST ({int(flow_z1)}% / {fan_m3h(flow_z1,VOL_Z1):.0f} m³/h)",
        line=dict(color=BLUE, width=3),
        fill='tozeroy', fillcolor=rgba_blue(0.13)))
    # Lüfterstufen-Treppenkurve (2. Achse)
    fig1.add_trace(go.Scatter(x=hours, y=fan_step_arr,
        name="Lüfterstufe [%]",
        line=dict(color=YELLOW, width=2, shape='hv'),  # shape='hv' = Treppe!
        yaxis='y2', opacity=0.9))
    # ── Peak-Werte berechnen (für Annotation über Kurve)
    c1_peak_idx = int(np.argmax(c1_arr))
    c1_peak_ppm = c1_arr[c1_peak_idx]
    c1_peak_h   = hours[c1_peak_idx]
    c1_peak_day = days[c1_peak_idx]
    c1_peak_rate = co2_rate_g_kg_h(c1_peak_day)  # g/kg/h am Scheitelpunkt

    # IST-Marker + Peak-Annotation
    vline_now(fig1, h_now, c1_ist, f"{c1_ist:.0f} ppm", BLUE)
    fig1.add_annotation(x=c1_peak_h, y=c1_peak_ppm,
        text=f"⌃ {c1_peak_ppm:.0f} ppm<br>{c1_peak_rate:.3f} g/kg/h",
        showarrow=True, arrowhead=2, arrowcolor=BLUE, arrowwidth=1.5,
        font=dict(color=BLUE, size=12, family="JetBrains Mono"),
        bgcolor="rgba(7,9,14,0.8)", bordercolor=BLUE, borderwidth=1,
        ax=0, ay=-45, xanchor="center")
    _ymax1 = max(max(c1_arr)*1.15, CO2_S3*1.1)
    fig1.update_layout(**base_layout(y_range=[0, _ymax1], title_y2="Lüfter [%]"))
    add_day_markers(fig1, _ymax1)
    st.plotly_chart(fig1, use_container_width=True)

    # ─────────────────────────────────────────────────
    # CHART 2 — NH3 Zone 01  (exponentiell!)
    # ─────────────────────────────────────────────────
    n1_ist = macro_nh3(mass_z1*1000, flow_z1, VOL_Z1, mast_day)
    n1_arr = [macro_nh3(mass_z1*1000, flow_z1, VOL_Z1, d) for d in days]
    n1_noq = [macro_nh3(mass_z1*1000, 20,      VOL_Z1, d) for d in days]
    ymax1  = max(max(n1_noq)*1.1, 55)
    _ym1   = min(ymax1, 65)

    # NH3 Peak = immer Tag 8 = hours[-1]
    n1_peak_ppm  = n1_arr[-1]
    n1_peak_rate = nh3_rate_g_kg_h(8.0) * 1000  # mg/kg/h

    st.markdown(
        f"<div class='sec red'>Zone 01 — NH₃ &nbsp;|&nbsp; IST: <b style='color:{ORANGE};'>{n1_ist:.1f} ppm</b>"
        f" &nbsp;|&nbsp; Lüfter: <b style='color:{YELLOW};'>{fan_m3h(flow_z1,VOL_Z1):.0f} m³/h</b></div>",
        unsafe_allow_html=True)

    fig2 = go.Figure()
    for y, col, lbl in [(5,MUTED,"5 ppm"),(10,MUTED,"10 ppm"),(15,MUTED,"15 ppm"),
                        (NH3_S1,GREEN,f"{NH3_S1} ppm — S1"),(NH3_S2,ORANGE,f"{NH3_S2} ppm — S2"),
                        (40,ORANGE,"40 ppm"),(NH3_S3,RED,f"{NH3_S3} ppm — ALARM")]:
        fig2.add_hline(y=y, line_color=col,
            line_dash="dash", line_width=1.0 if y not in [NH3_S1,NH3_S2,NH3_S3] else 1.8,
            annotation_text=lbl, annotation_font=dict(color=col, size=11),
            annotation_position="right")
    fig2.add_trace(go.Scatter(
        x=np.concatenate([hours, hours[::-1]]),
        y=np.concatenate([n1_noq, n1_arr[::-1]]),
        fill='toself', fillcolor=rgba_red(0.07),
        line=dict(color='rgba(0,0,0,0)'),
        name="Risiko ohne Lüftung", showlegend=True))
    fan_step_nh3 = []
    for nh3_val in n1_arr:
        if   nh3_val >= stufen_nh3[3]: fan_step_nh3.append(stufen_pct[3])
        elif nh3_val >= stufen_nh3[2]: fan_step_nh3.append(stufen_pct[2])
        elif nh3_val >= stufen_nh3[1]: fan_step_nh3.append(stufen_pct[1])
        else:                          fan_step_nh3.append(stufen_pct[0])
    fig2.add_trace(go.Scatter(x=hours, y=n1_arr,
        name=f"NH₃ IST ({int(flow_z1)}% / {fan_m3h(flow_z1,VOL_Z1):.0f} m³/h)",
        line=dict(color=ORANGE, width=3.5),
        fill='tozeroy', fillcolor=rgba_orange(0.14)))
    fig2.add_trace(go.Scatter(x=hours, y=fan_step_nh3,
        name="Lüfterstufe NH₃ [%]",
        line=dict(color=YELLOW, width=2, shape='hv'),
        yaxis='y2', opacity=0.9))
    fig2.add_vrect(x0=72, x1=288, fillcolor=rgba_red(0.05), line_width=0)
    # Peak-Annotation NH3 (Scheitelpunkt = Tag 8 = Ende)
    _n1_ann_y = min(n1_peak_ppm, _ym1 * 0.92)
    fig2.add_annotation(x=hours[-1], y=_n1_ann_y,
        text=f"⌃ {n1_peak_ppm:.1f} ppm<br>{n1_peak_rate:.3f} mg/kg/h",
        showarrow=True, arrowhead=2, arrowcolor=ORANGE, arrowwidth=1.5,
        font=dict(color=ORANGE, size=12, family="JetBrains Mono"),
        bgcolor="rgba(7,9,14,0.8)", bordercolor=ORANGE, borderwidth=1,
        ax=-55, ay=-35, xanchor="right")
    fig2.add_annotation(x=73, y=_ym1*0.75, text="↑ Exponentialphase ab Tag 4",
        showarrow=False, font=dict(color=RED, size=12, family="JetBrains Mono"), xanchor="left")
    vline_now(fig2, h_now, n1_ist, f"{n1_ist:.1f} ppm", ORANGE)
    fig2.update_layout(**base_layout(y_range=None, title_y2="Lüfter [%]", nh3=True, log=True))
    add_day_markers(fig2, _ym1)
    st.plotly_chart(fig2, use_container_width=True)

    # ─────────────────────────────────────────────────
    # CHART 3 — CO2 Zone 02
    # ─────────────────────────────────────────────────
    c2_ist = macro_co2(mass_z2*1000, flow_z2, VOL_Z2, mast_day)
    c2_arr = [macro_co2(mass_z2*1000, flow_z2, VOL_Z2, d) for d in days]
    q2     = fan_m3h_z2(flow_z2)

    c2_peak_idx  = int(np.argmax(c2_arr))
    c2_peak_ppm  = c2_arr[c2_peak_idx]
    c2_peak_h    = hours[c2_peak_idx]
    c2_peak_rate = co2_rate_g_kg_h(days[c2_peak_idx])

    st.markdown(
        f"<div class='sec'>Zone 02 — CO₂ &nbsp;|&nbsp; IST: <b style='color:{GREEN};'>{c2_ist:.0f} ppm</b>"
        f" &nbsp;|&nbsp; Lüfter: <b style='color:{YELLOW};'>{q2:.0f} m³/h</b></div>",
        unsafe_allow_html=True)

    fig3 = go.Figure()
    for y, col, lbl in [(CO2_S1,GREEN,f"{CO2_S1:,} ppm"),(CO2_S2,ORANGE,f"{CO2_S2:,} ppm"),(CO2_S3,RED,f"{CO2_S3:,} ppm — ALARM")]:
        fig3.add_hline(y=y, line_color=col, line_dash="dash", line_width=1.5,
            annotation_text=lbl, annotation_font=dict(color=col, size=12),
            annotation_position="right")
    fig3.add_trace(go.Scatter(x=hours, y=c2_arr,
        name=f"CO₂ Z02 ({int(flow_z2)}% / {q2:.0f} m³/h)",
        line=dict(color=GREEN, width=3),
        fill='tozeroy', fillcolor=rgba_green(0.13)))
    vline_now(fig3, h_now, c2_ist, f"{c2_ist:.0f} ppm", GREEN)
    fig3.add_annotation(x=c2_peak_h, y=c2_peak_ppm,
        text=f"⌃ {c2_peak_ppm:.0f} ppm<br>{c2_peak_rate:.3f} g/kg/h",
        showarrow=True, arrowhead=2, arrowcolor=GREEN, arrowwidth=1.5,
        font=dict(color=GREEN, size=12, family="JetBrains Mono"),
        bgcolor="rgba(7,9,14,0.8)", bordercolor=GREEN, borderwidth=1,
        ax=0, ay=-45, xanchor="center")
    _ymax3 = max(max(c2_arr)*1.15, CO2_S3*1.1)
    fig3.update_layout(**base_layout(y_range=[0, _ymax3]))
    add_day_markers(fig3, _ymax3)
    st.plotly_chart(fig3, use_container_width=True)

    # ─────────────────────────────────────────────────
    # CHART 4 — NH3 Zone 02
    # ─────────────────────────────────────────────────
    n2_ist = macro_nh3(mass_z2*1000, flow_z2, VOL_Z2, mast_day)
    n2_arr = [macro_nh3(mass_z2*1000, flow_z2, VOL_Z2, d) for d in days]
    n2_noq = [macro_nh3(mass_z2*1000, 20,      VOL_Z2, d) for d in days]
    ymax2  = max(max(n2_noq)*1.1, 55)
    _ym2   = min(ymax2, 65)

    n2_peak_ppm  = n2_arr[-1]
    n2_peak_rate = nh3_rate_g_kg_h(8.0) * 1000

    st.markdown(
        f"<div class='sec red'>Zone 02 — NH₃ &nbsp;|&nbsp; IST: <b style='color:{YELLOW};'>{n2_ist:.1f} ppm</b>"
        f" &nbsp;|&nbsp; Lüfter: <b style='color:{YELLOW};'>{q2:.0f} m³/h</b></div>",
        unsafe_allow_html=True)

    fig4 = go.Figure()
    for y, col, lbl in [(5,MUTED,"5 ppm"),(10,MUTED,"10 ppm"),(15,MUTED,"15 ppm"),
                        (NH3_S1,GREEN,f"{NH3_S1} ppm — S1"),(NH3_S2,ORANGE,f"{NH3_S2} ppm — S2"),
                        (40,ORANGE,"40 ppm"),(NH3_S3,RED,f"{NH3_S3} ppm — ALARM")]:
        fig4.add_hline(y=y, line_color=col,
            line_dash="dash", line_width=1.0 if y not in [NH3_S1,NH3_S2,NH3_S3] else 1.8,
            annotation_text=lbl, annotation_font=dict(color=col, size=11),
            annotation_position="right")
    fig4.add_trace(go.Scatter(
        x=np.concatenate([hours, hours[::-1]]),
        y=np.concatenate([n2_noq, n2_arr[::-1]]),
        fill='toself', fillcolor=rgba_red(0.07),
        line=dict(color='rgba(0,0,0,0)'),
        name="Risiko ohne Lüftung", showlegend=True))
    fig4.add_trace(go.Scatter(x=hours, y=n2_arr,
        name=f"NH₃ Z02 ({int(flow_z2)}% / {q2:.0f} m³/h)",
        line=dict(color=YELLOW, width=3.5),
        fill='tozeroy', fillcolor=rgba_yellow(0.14)))
    fig4.add_vrect(x0=72, x1=288, fillcolor=rgba_red(0.05), line_width=0)
    _n2_ann_y = min(n2_peak_ppm, _ym2 * 0.92)
    fig4.add_annotation(x=hours[-1], y=_n2_ann_y,
        text=f"⌃ {n2_peak_ppm:.1f} ppm<br>{n2_peak_rate:.3f} mg/kg/h",
        showarrow=True, arrowhead=2, arrowcolor=YELLOW, arrowwidth=1.5,
        font=dict(color=YELLOW, size=12, family="JetBrains Mono"),
        bgcolor="rgba(7,9,14,0.8)", bordercolor=YELLOW, borderwidth=1,
        ax=-55, ay=-35, xanchor="right")
    fig4.add_annotation(x=73, y=_ym2*0.75, text="↑ Exponentialphase ab Tag 4",
        showarrow=False, font=dict(color=RED, size=12, family="JetBrains Mono"), xanchor="left")
    vline_now(fig4, h_now, n2_ist, f"{n2_ist:.1f} ppm", YELLOW)
    fig4.update_layout(**base_layout(y_range=None, title_y2="Lüfter [%]", nh3=True, log=True))
    add_day_markers(fig4, _ym2)
    st.plotly_chart(fig4, use_container_width=True)

# ── SCHALTSTUFEN & INFO — VOLLE BREITE UNTEN ──────
_snames  = ["ECO", "STUFE 1", "STUFE 2", "ALARM"]
_scols   = [MUTED, GREEN, ORANGE, RED]
_co2_lbl = [f"{_snames[i]}\n{stufen_pct[i]}%" for i in range(4)]
_nh3_lbl = [f"{_snames[i]}\n{'<' if i==0 else ''}{stufen_nh3[i]} ppm" for i in range(4)]

aktiv        = [fs_nr == i for i in range(4)]
nh3_aktiv_nr = 0 if nh3_z1<stufen_nh3[1] else 1 if nh3_z1<stufen_nh3[2] else 2 if nh3_z1<stufen_nh3[3] else 3
bar_cols_co2 = [_scols[i] if aktiv[i]        else "#0F1825" for i in range(4)]
bar_cols_nh3 = [_scols[i] if i<=nh3_aktiv_nr else "#0F1825" for i in range(4)]

def _stage_layout(ytitle, yrange):
    return dict(
        height=300, paper_bgcolor=DARK, plot_bgcolor=DARK,
        xaxis=dict(color=WHITE, gridcolor='rgba(0,0,0,0)',
                   tickfont=dict(size=12, family="JetBrains Mono")),
        yaxis=dict(title=ytitle, color=WHITE, gridcolor=BORDER,
                   range=yrange, tickfont=dict(size=11),
                   title_font=dict(size=11, color=WHITE)),
        font=dict(color=WHITE, family="JetBrains Mono"),
        showlegend=False, margin=dict(l=55, r=15, t=28, b=8))

_sc1, _sc2 = st.columns(2)

with _sc1:
    st.markdown(f"<div class='sec'>CO\u2082-Lüfterstufen Zone 01</div>", unsafe_allow_html=True)
    _co2_ys   = [stufen_pct[0],
                 stufen_pct[1] - stufen_pct[0],
                 stufen_pct[2] - stufen_pct[1],
                 stufen_pct[3] - stufen_pct[2]]
    _co2_base = [0, stufen_pct[0], stufen_pct[1], stufen_pct[2]]
    fig_stages = go.Figure()
    _aktiv_txt = ["▶ " if aktiv[i] else "" for i in range(4)]
    fig_stages.add_trace(go.Bar(
        x=_co2_lbl, y=_co2_ys, base=_co2_base,
        marker=dict(color=bar_cols_co2, line=dict(color=_scols, width=2)),
        text=[f"{_aktiv_txt[i]}{stufen_pct[i]}%" for i in range(4)],
        textfont=dict(color=WHITE, size=13, family="JetBrains Mono"),
        textposition='inside', width=0.6,
    ))
    for i in range(1, 4):
        fig_stages.add_annotation(
            x=_co2_lbl[i], y=stufen_pct[i] + 4,
            text=f"CO\u2082 > {stufen_co2[i]:,} ppm",
            showarrow=False,
            font=dict(color=_scols[i], size=10, family="JetBrains Mono"))
    fig_stages.add_hline(y=flow_z1, line_color=YELLOW, line_dash="dash", line_width=1.5,
        annotation_text=f"  aktuell: {flow_z1:.0f}%",
        annotation_font=dict(color=YELLOW, size=10, family="JetBrains Mono"),
        annotation_position="right")
    fig_stages.update_layout(**_stage_layout("Lüfterstärke [%]", [0, max(stufen_pct)*1.22]))
    st.plotly_chart(fig_stages, use_container_width=True)

with _sc2:
    st.markdown(f"<div class='sec red' style='margin-top:4px;'>NH\u2083-Schwellen Zone 01</div>", unsafe_allow_html=True)
    _nh3_tops = [stufen_nh3[1], stufen_nh3[2], stufen_nh3[3], stufen_nh3[3]*1.6]
    _nh3_ys   = [_nh3_tops[i] - (stufen_nh3[i] if i>0 else 0) for i in range(4)]
    _nh3_base = [0, stufen_nh3[1], stufen_nh3[2], stufen_nh3[3]]
    _nh3_anno = [stufen_nh3[1], stufen_nh3[2], stufen_nh3[3], int(stufen_nh3[3]*1.6)]
    fig_ns = go.Figure()
    fig_ns.add_trace(go.Bar(
        x=_nh3_lbl, y=_nh3_ys, base=_nh3_base,
        marker=dict(color=bar_cols_nh3, line=dict(color=_scols, width=2)),
        text=[f"{_nh3_anno[i]} ppm" for i in range(4)],
        textfont=dict(color=WHITE, size=12, family="JetBrains Mono"),
        textposition='inside', width=0.6,
    ))
    fig_ns.add_hline(y=nh3_z1, line_color=YELLOW, line_dash="dash", line_width=2,
        annotation_text=f"  aktuell: {nh3_z1:.1f} ppm",
        annotation_font=dict(color=YELLOW, size=10, family="JetBrains Mono"),
        annotation_position="right")
    _nh3_ymax = stufen_nh3[3] * 1.75
    fig_ns.update_layout(**_stage_layout("NH\u2083 [ppm]", [0, _nh3_ymax]))
    st.plotly_chart(fig_ns, use_container_width=True)

# Technische Parameter
co2_prod  = (mass_z1 * 1000 * co2_rate_g_kg_h(mast_day)) / 1000
nh3_prod  = (mass_z1 * 1000 * nh3_rate_g_kg_h(mast_day))
nh3_end_v = nh3_rate_g_kg_h(8.0)*1000
factor_v  = nh3_end_v / max(nh3_rate_g_kg_h(mast_day)*1000, 0.01)
st.markdown(f"""<div class='infobox'>
<h5>Lastenheft &amp; Simulation — Tag {mast_day:.1f}</h5>
<table style='width:100%;font-size:.92rem;border-collapse:collapse;line-height:2.0;'>
<tr><td class='lb'>Volumen Z1</td><td class='v'>{VOL_Z1:.0f} m³</td></tr>
<tr><td class='lb'>Larvenmasse Z1</td><td class='v'>{mass_z1:.1f} t</td></tr>
<tr><td class='lb'>CO\u2082-Produktion</td><td class='v'>{co2_prod:.2f} kg/h</td></tr>
<tr><td class='lb'>NH\u2083-Produktion</td><td class='v'>{nh3_prod:.0f} g/h</td></tr>
<tr><td class='lb'>Luftwechsel Z1</td><td class='v'>{ach(flow_z1,VOL_Z1):.2f} /h</td></tr>
<tr><td class='lb'>NH\u2083 Anstiegsfaktor</td><td class='v' style='color:{RED};'>{factor_v:.1f}×</td></tr>
<tr><td class='lb'>Z1 Soll-Temp.</td><td class='v'>max. 10 °C</td></tr>
<tr><td class='lb'>Liefertermin</td><td class='v' style='color:{YELLOW};'>10.06.2026</td></tr>
</table></div>""", unsafe_allow_html=True)

if os.path.exists("facility_layout.png"):
    st.image("facility_layout.png", use_container_width=True,
             caption="14x40ft Container | Zone 01+02 | Steyerberg")


st.divider()

# ── 3D VISUALISIERUNG — VOLLE BREITE UNTEN ────────
st.markdown("<div class='sec'>3D Luftstrom Zone 01 — Zuluft oben vorne · CO₂-Abluft Boden hinten · NH₃-Abluft Deckenkanal</div>", unsafe_allow_html=True)

if True:
    fan_pct = max(flow_z1, 5) / 100.0
    n_pts   = 40
    t = np.linspace(0, 1, n_pts)

    # ── ZULUFT: oben vorne links (x=0, y=0, z=H) ─────────────────
    # Strom fächert sich von der Einblasecke aus im Raum auf
    # Hauptströmungsrichtung: x=0→L, leicht abfallend in z
    # NH3-Schicht: bleibt oben, wird hinten per Deckenkanal abgeführt
    # CO2-Schicht: sinkt ab, wird bodennah hinten abgesaugt

    fig3 = go.Figure()

    # ── Stromfäden: Zuluft oben vorne links ──────────────────────
    # Mehrere Fäden fächern sich tangential aus
    # Format: (y_start, y_end, z_start, z_end, lw)
    zuluft_streams = [
        # Hauptstrom — fächert sich über die Raumbreite
        (0.3,  Z1_B*0.15, Z1_H*0.92, Z1_H*0.75, 8),
        (0.5,  Z1_B*0.30, Z1_H*0.90, Z1_H*0.65, 9),
        (0.7,  Z1_B*0.50, Z1_H*0.88, Z1_H*0.55, 9),
        (1.0,  Z1_B*0.65, Z1_H*0.86, Z1_H*0.45, 8),
        (1.4,  Z1_B*0.78, Z1_H*0.84, Z1_H*0.38, 7),
        (1.8,  Z1_B*0.88, Z1_H*0.82, Z1_H*0.32, 6),
    ]

    for (y0, y1, z0, z1e, lw_max) in zuluft_streams:
        x_path = t * Z1_L
        y_path = np.clip(y0 + (y1 - y0) * t, 0.05, Z1_B - 0.05)
        z_path = z0 + (z1e - z0) * t

        # Querschnitt: breit am Anfang (Aufweitung), dann normalisiert
        width = 0.2 + 0.8 * np.sin(np.pi * t * 0.6 + 0.1) ** 0.5

        for i in range(n_pts - 1):
            # Temperatur: KALT (blau) rein → aufwärmen im Raum (orange Mitte) → 
            # wird von Verdampfer wieder gekühlt (blau Ende)
            v = np.sin(np.pi * t[i] * 0.85)   # kalt→warm→kühl
            r_c = int(54  + (240 - 54)  * v)
            g_c = int(169 + (100 - 169) * v)
            b_c = int(225 + (40  - 225) * v)
            lw  = max(1.5, lw_max * width[i] * fan_pct)
            fig3.add_trace(go.Scatter3d(
                x=[x_path[i], x_path[i+1]],
                y=[y_path[i], y_path[i+1]],
                z=[z_path[i], z_path[i+1]],
                mode='lines',
                line=dict(color=f"rgba({r_c},{g_c},{b_c},{0.82*fan_pct})", width=lw),
                showlegend=False, hoverinfo='none',
            ))

    # ── CO2-Absinkströmung: bodennah zur Abluft hinten unten ─────
    co2_sinks = [
        (Z1_B*0.2, Z1_B*0.15, Z1_H*0.40, 0.12, 5),
        (Z1_B*0.5, Z1_B*0.45, Z1_H*0.35, 0.10, 6),
        (Z1_B*0.8, Z1_B*0.75, Z1_H*0.30, 0.08, 5),
    ]
    for (y0, y1, z_top, z_bot, lw_max) in co2_sinks:
        x_path = t * Z1_L
        y_path = y0 + (y1 - y0) * t
        z_path = z_top + (z_bot - z_top) * t   # absinken

        for i in range(n_pts - 1):
            progress = t[i]   # CO2 wird gasreicher → dunkler orange/rot
            r_c = int(255 * min(1.0, progress * 1.5))
            g_c = int(100 * (1 - progress * 0.6))
            b_c = int(40)
            alph = 0.5 * fan_pct * progress   # erst unsichtbar, dann sichtbarer
            lw   = max(1.2, lw_max * fan_pct * (0.3 + 0.7 * progress))
            fig3.add_trace(go.Scatter3d(
                x=[x_path[i], x_path[i+1]],
                y=[y_path[i], y_path[i+1]],
                z=[z_path[i], z_path[i+1]],
                mode='lines',
                line=dict(color=f"rgba({r_c},{g_c},{b_c},{alph})", width=lw),
                showlegend=False, hoverinfo='none',
            ))

    # ── NH3-Deckenkanal: bleibt oben, wird hinten abgeführt ──────
    nh3_ceiling = [
        (Z1_B*0.1, Z1_B*0.08, Z1_H*0.95, Z1_H*0.92, 4),
        (Z1_B*0.4, Z1_B*0.35, Z1_H*0.93, Z1_H*0.90, 5),
        (Z1_B*0.7, Z1_B*0.65, Z1_H*0.94, Z1_H*0.91, 4),
    ]
    for (y0, y1, z0, z1e, lw_max) in nh3_ceiling:
        x_path = t * Z1_L
        y_path = y0 + (y1 - y0) * t
        z_path = z0 + (z1e - z0) * t

        for i in range(n_pts - 1):
            progress = t[i]
            r_c = int(255 * min(1.0, progress))
            g_c = int(209 * (1 - progress * 0.5))
            b_c = int(102 * (1 - progress * 0.7))
            alph = 0.45 * fan_pct * (0.2 + 0.8 * progress)
            lw   = max(1.0, lw_max * fan_pct)
            fig3.add_trace(go.Scatter3d(
                x=[x_path[i], x_path[i+1]],
                y=[y_path[i], y_path[i+1]],
                z=[z_path[i], z_path[i+1]],
                mode='lines',
                line=dict(color=f"rgba({r_c},{g_c},{b_c},{alph})", width=lw),
                showlegend=False, hoverinfo='none',
            ))

    # ── Gaskörper (Volumen) ──────────────────────────────────────
    nx, ny, nz = 10, 7, 5
    xv, yv, zv = np.meshgrid(
        np.linspace(0,Z1_L,nx), np.linspace(0,Z1_B,ny),
        np.linspace(0,Z1_H,nz), indexing='ij')
    co2n = np.clip(co2_z1/10000.0, 0, 1)
    nh3n = np.clip(nh3_z1/50.0,   0, 1)
    # CO2 bodennah, steigt von vorne nach hinten
    gas_co2 = co2n * (1 - zv/Z1_H)**2.5 * (0.3 + 0.7*(xv/Z1_L))
    # NH3 deckennah, steigt von vorne nach hinten
    gas_nh3 = nh3n * (zv/Z1_H)**2.0    * (0.3 + 0.7*(xv/Z1_L))
    gas = gas_co2 + gas_nh3
    fig3.add_trace(go.Volume(
        x=xv.flatten(), y=yv.flatten(), z=zv.flatten(),
        value=gas.flatten(),
        isomin=0.04, isomax=0.70, opacity=0.10, surface_count=8,
        colorscale=[
            [0.0, "rgba(10,20,60,0)"],
            [0.3, "rgba(54,169,225,0.18)"],
            [0.6, "rgba(255,155,66,0.40)"],
            [1.0, "rgba(239,71,111,0.70)"],
        ],
        showscale=False,
    ))

    # ── Raumkanten ───────────────────────────────────────────────
    C = [(0,0,0),(Z1_L,0,0),(0,Z1_B,0),(Z1_L,Z1_B,0),
         (0,0,Z1_H),(Z1_L,0,Z1_H),(0,Z1_B,Z1_H),(Z1_L,Z1_B,Z1_H)]
    for ii,jj in [(0,1),(0,2),(1,3),(2,3),(4,5),(4,6),(5,7),(6,7),(0,4),(1,5),(2,6),(3,7)]:
        fig3.add_trace(go.Scatter3d(
            x=[C[ii][0],C[jj][0]], y=[C[ii][1],C[jj][1]], z=[C[ii][2],C[jj][2]],
            mode='lines', line=dict(color="#1a3045",width=1.5),
            showlegend=False, hoverinfo='none'))

    # ── Markierungen: Zu- und Abluft ────────────────────────────
    fig3.add_trace(go.Scatter3d(
        x=[0.5,     Z1_L-0.5,     Z1_L-0.5],
        y=[0.5,     Z1_B-0.5,     Z1_B-0.5],
        z=[Z1_H-0.2, 0.15,        Z1_H-0.15],
        mode='markers+text',
        text=["ZULUFT<br>oben", "CO₂-ABL<br>Boden", "NH₃-ABL<br>Deckenkanal"],
        textfont=dict(color=WHITE, size=11),
        textposition=['middle right','middle left','middle left'],
        marker=dict(size=[14,11,11],
                    color=[BLUE, RED, YELLOW],
                    symbol=['circle','square','diamond']),
        showlegend=False,
    ))

    # ── Verdampfer-Symbol hinten oben Mitte ─────────────────────
    fig3.add_trace(go.Scatter3d(
        x=[Z1_L-0.3, Z1_L-0.3],
        y=[Z1_B*0.3,  Z1_B*0.7],
        z=[Z1_H-0.3,  Z1_H-0.3],
        mode='lines+markers',
        line=dict(color=f"rgba(54,169,225,0.6)", width=6),
        marker=dict(size=4, color=BLUE),
        showlegend=False, hoverinfo='none',
        name='Verdampfer'
    ))
    fig3.add_trace(go.Scatter3d(
        x=[Z1_L-0.3], y=[Z1_B*0.5], z=[Z1_H-0.4],
        mode='text',
        text=["VERDAMPFER"],
        textfont=dict(color=BLUE, size=10),
        showlegend=False,
    ))

    fig3.update_layout(
        scene=dict(
            xaxis=dict(title="L [m]", color=WHITE, gridcolor=BORDER, backgroundcolor=DARK),
            yaxis=dict(title="B [m]", color=WHITE, gridcolor=BORDER, backgroundcolor=DARK),
            zaxis=dict(title="H [m]", color=WHITE, gridcolor=BORDER, backgroundcolor=DARK),
            bgcolor=DARK,
            camera=dict(eye=dict(x=1.8, y=-1.6, z=0.9)),
            aspectmode='data',
        ),
        paper_bgcolor=DARK, margin=dict(l=0,r=0,b=0,t=0), height=560,
    )
    st.plotly_chart(fig3, use_container_width=True)


# ── RECHTE SPALTE: alle 4 Grafiken übereinander ──
# ── FOOTER ────────────────────────────────────────────────────
st.divider()

# ── PDF BERICHT ───────────────────────────────────────────────
_pdf_col, _foot_col = st.columns([1, 2])
with _pdf_col:
    if st.button("📄 PDF-Bericht erstellen", use_container_width=True, type="primary"):
        _pdf_params = dict(
            vol_z1=VOL_Z1, vol_z2=VOL_Z2,
            mass_z1=mass_z1, mass_z2=mass_z2,
            mast_day=mast_day, h_now=(mast_day-1)*24,
            q1=fan_m3h(flow_z1, VOL_Z1), pct1=int(flow_z1),
            q2=fan_m3h_z2(flow_z2),
            ach1=ach_val(flow_z1, VOL_Z1), ach2=ach_val(flow_z2, VOL_Z2),
            co2_rate=CO2_RATE_AVG, nh3_rate=NH3_RATE_BASE,
            co2_z1=co2_z1, nh3_z1=nh3_z1,
            co2_z2=co2_z2, nh3_z2=nh3_z2,
            co2_s1=CO2_S1, co2_s2=CO2_S2, co2_s3=CO2_S3,
            nh3_s1=NH3_S1, nh3_s2=NH3_S2, nh3_s3=NH3_S3,
            s_pct=stufen_pct, s_co2=stufen_co2, s_nh3=stufen_nh3,
        )
        _pdf_bytes = generate_pdf_report(_pdf_params)
        _fname = f"BSF_GasSim_Tag{mast_day:.1f}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        st.download_button(
            label="⬇ PDF herunterladen",
            data=_pdf_bytes,
            file_name=_fname,
            mime="application/pdf",
            use_container_width=True,
        )

with _foot_col:
    st.markdown(f"""
<div style='display:flex;justify-content:space-between;padding-top:8px;'>
  <div class='foot'>BSF GAS-SIMULATOR v5.0 &nbsp;|&nbsp; °coolsulting × REPLOID Group AG &nbsp;|&nbsp; LP 640_07 Rev.02</div>
  <div class='foot'>Quellen: Global 2000 (2024), Chen et al. 2019 (Brill), Engineering For Change</div>
</div>
""", unsafe_allow_html=True)

# ── AUTOPILOT LOOP ────────────────────────────────────────────
if st.session_state.sim_active:
    time.sleep(0.25)
    st.rerun()
