# BSF KÜHLLAGER GAS-SIMULATOR
## App-Beschreibung & Zusammenfassung
**Version 5.2** · Projekt LP 640_07 Rev.02
**REPLOID Group AG × coolsulting e.U. × Polar Energy Leithinger GmbH**

---

## Zweck

Der BSF Gas-Simulator ist ein interaktives Verkaufs- und Planungswerkzeug für die intelligente Lüftungssteuerung in **Black Soldier Fly (BSF) Larvenkühlanlagen**. Er simuliert die Gaskonzentration (CO₂ und NH₃) in Abhängigkeit von Larvenmasse, Lüfterleistung und Masttag — und zeigt in Echtzeit, wie das Lüftungssystem reagieren muss.

---

## Technische Basis

| Parameter | Wert |
|---|---|
| Zone 01 Volumen | 790,7 m³ (21,36 × 9,75 × 3,80 m) |
| Zone 02 Volumen | 42,0 m³ (3,80 × 2,90 × 3,80 m) |
| Zone 01 max. Lüfter | 4.748 m³/h (6 ACH bei 100%) |
| Zone 02 max. Lüfter | 200 m³/h |
| Max. Substrat Zone 01 | 51.858 kg (201 Boxen × 258 kg) |
| Max. Substrat Zone 02 | 7.560 kg (63 Boxen × 120 kg) |
| Mastzyklus | 8 Tage |
| Zeitachse Simulation | 0–96 Stunden |

---

## Physikalisches Modell

### CO₂-Emissionsrate
```
E_CO2(t) = CO2_RATE_AVG × (0.3 + 2.7 × sin(π × t/8)^1.8)
```
Glockenform mit Peak an Tag 4. Durchschnitt: **0,125 g/kg/h** → Peak: ~0,375 g/kg/h

### NH₃-Emissionsrate
```
t < Tag 4:  E_NH3(t) = BASE × (1 + 0.5 × t/3.6)
t ≥ Tag 4:  E_NH3(t) = BASE × 1.5 × exp(2.6 × (t/8 − 0.45))
```
Exponentieller Anstieg ab Tag 4. Basis: **0,0002 g/kg/h** → Peak Tag 8: ~0,044 mg/kg/h

### Massenbilanz-Gleichung (für beide Gase)
```
c [ppm] = c_Außenluft + (Ṁ_Gas [m³/h] ÷ Q_Lüfter [m³/h]) × 10⁶
```

---

## Grenzwerte

### CO₂
| Stufe | Schwelle | Lüfter |
|---|---|---|
| ECO | 420 ppm (Außenluft) | 20% |
| STUFE 1 | > 3.000 ppm | 40% |
| STUFE 2 | > 5.000 ppm | 70% |
| ALARM | > 10.000 ppm | 100% |

### NH₃
| Stufe | Schwelle | Lüfter |
|---|---|---|
| ECO | < 12 ppm | 20% |
| STUFE 1 | 12 ppm | 40% |
| STUFE 2 | 25 ppm | 70% |
| ALARM | > 50 ppm | 100% |

> Alle Schwellenwerte sind in der Sidebar editierbar.

---

## App-Aufbau

### Sidebar (links)
| Bereich | Funktion |
|---|---|
| **RAUMPARAMETER** | Abmessungen Z1/Z2, Boxen, kg/Box |
| **SIMULATION** | Start/Stop Echtzeit, Masttag-Slider |
| **LÜFTERSTUFEN** | 4 editierbare Stufen: CO₂ ppm / NH₃ ppm / Lüfter % |
| **LÜFTER MANUELL** | Radio-Stufe + Feinjustierung ±15% für Z1 und Z2 |
| **EMISSIONSRATEN** | CO₂ Ø g/kg/h und NH₃ Basis g/kg/h editierbar |
| **PDF BERICHT** | Einknopf-Generierung des vollständigen Berichts |
| **AUTOPILOT** | Automatische Stufenschaltung nach Gasschwellen |

### Hauptbereich (Diagramme)
Vier Zeitreihen-Diagramme (0–96 Stunden):

| Chart | Gas | Zone | Farbe |
|---|---|---|---|
| 1 | CO₂ | Zone 01 | Blau |
| 2 | NH₃ | Zone 01 | Orange |
| 3 | CO₂ | Zone 02 | Grün |
| 4 | NH₃ | Zone 02 | Gelb |

Jedes Diagramm zeigt:
- Errechnete ppm-Kurve (reaktiv auf alle Slider)
- Schwellenwert-Linien (farbcodiert)
- IST-Marker (aktueller Masttag)
- Scheitelpunkt-Annotation mit g/kg/h Emissionsrate
- Lüfter-Treppenkurve (2. Y-Achse)

### Rechte Spalte (Schaltstufen)
- **CO₂-Lüfterstufen Balkendiagramm** — gestapelt, aktive Stufe markiert
- **NH₃-Schwellen Balkendiagramm** — gestapelt, IST-Linie gelb
- **Technische Parameter** — Live-Kennzahlen (Produktion, ACH, Anstiegsfaktor)

---

## PDF-Bericht

Auf Knopfdruck generierter 4-seitiger A4-Bericht:

| Seite | Inhalt |
|---|---|
| 1 | Deckblatt, KPI-Tabelle, Raumparameter, Gastabelle, Lüfterstufen |
| 2 | Zone 01 — CO₂ + NH₃ Diagramme, Kubaturberechnung |
| 3 | Zone 02 — CO₂ + NH₃ Diagramme, Kubaturberechnung |
| 4 | Haftungsausschluss, Signaturen |

Kopfzeile: °coolsulting Logo rechts oben
Fußzeile: Polar Energy Leithinger GmbH + Coolsulting e.U. Adressen, © coolsulting

---

## Installation & Start

```bash
# 1. Virtuelle Umgebung aktivieren
venv\Scripts\activate          # Windows
source venv/bin/activate       # Mac/Linux

# 2. Abhängigkeiten installieren
pip install streamlit plotly numpy reportlab

# 3. App starten
streamlit run BSF_GasSim_v52.py
# oder
python -m streamlit run BSF_GasSim_v52.py
```

### requirements.txt
```
streamlit>=1.32
plotly>=5.18
numpy>=1.24
reportlab>=4.0
```

---

## Dateien

| Datei | Beschreibung |
|---|---|
| `BSF_GasSim_v52.py` | Haupt-App |
| `coolsulting_logo_white.png` | Logo für PDF-Kopfzeile (selber Ordner) |
| `requirements.txt` | Python-Abhängigkeiten |

---

## Erweiterungsmöglichkeiten

Das System ist für weitere Gase vorbereitet. Die Funktion `gas_chart_rl()` im PDF-Generator akzeptiert beliebige Gase mit eigenem Parameter-Set:

```python
gas_chart_rl(
    gas_name='CH4',        # Bezeichnung
    mass_kg=...,           # Larvenmasse in kg
    flow_pct=...,          # Lüfter in %
    vol=...,               # Raumvolumen in m³
    rate_fn=...,           # Emissionsrate-Funktion (day) -> g/kg/h
    rho=0.657,             # Gasdichte kg/m³
    ambient=0.0,           # Hintergrundkonzentration ppm
    thresholds=[...],      # [(ppm, label), ...]
)
```

Geplante zukünftige Gase: **CH₄** (Methan), **H₂S** (Schwefelwasserstoff), **CO** (Kohlenmonoxid)

---

## Quellen & Normen

- Global 2000 / Friends of the Earth Austria (2024): *BSF Emissionsmesskampagne*
- Chen et al. (2019): *Greenhouse gas emissions from black soldier fly larvae composting*
- VDI 6022: Raumlufttechnik, Raumluftqualität
- GESTIS Stoffdatenbank: MAK-Werte CO₂ (5.000 ppm) und NH₃ (20 ppm)

---

*© coolsulting e.U. · Mozartstraße 11 · 4020 Linz · Österreich*
*In Zusammenarbeit mit Polar Energy Leithinger GmbH · Dr.-Groß-Str. 36-38 · 4600 Wels*
