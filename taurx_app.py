import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime
import numpy as np
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- PAGE CONFIG ---
st.set_page_config(page_title="TAURX Dashboard", layout="wide", page_icon="🏃")

# --- 1. LOGIN & AUTHENTIFIZIERUNG ---
CLIENT_ID = st.secrets["STRAVA_CLIENT_ID"]
CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = "https://taurx-app-mkgvikh6guv7o4cjrmetjm.streamlit.app"

def get_login_url():
    return f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&approval_prompt=force&scope=activity:read_all"

def exchange_token(auth_code):
    url = "https://www.strava.com/oauth/token"
    payload = {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'code': auth_code, 'grant_type': 'authorization_code'}
    return requests.post(url, data=payload).json()

# --- DATENLADE-FUNKTION (Nutzt dynamischen Token) ---
@st.cache_data(show_spinner="Lade Laufdaten von Strava...")
def load_all_runs(token):
    header = {'Authorization': f"Bearer {token}"}
    act_url = "https://www.strava.com/api/v3/athlete/activities"
    all_activities = []
    page = 1
    
    while page <= 4:  # Deckt ca. 800 Aktivitäten ab
        res = requests.get(act_url, headers=header, params={'per_page': 200, 'page': page})
        if res.status_code != 200 or not res.json():
            break
        all_activities.extend(res.json())
        page += 1
        
    run_list = []
    for act in all_activities:
        if act.get('type') != 'Run' or not act.get('has_heartrate'):
            continue
            
        hr = act.get('average_heartrate', 0)
        moving_time_min = act.get('moving_time', 0) / 60
        dist_m = act.get('distance', 0)
        elev_m = act.get('total_elevation_gain', 0)
        
        if moving_time_min == 0 or hr == 0:
            continue
            
        speed_kmh = (dist_m / 1000) / (moving_time_min / 60)
        ef = (dist_m / moving_time_min) / hr
        gaef = ((dist_m + elev_m * 10) / moving_time_min) / hr
        cadence = act.get('average_cadence', 0)
        spm = cadence * 2 if cadence > 0 else None
        
        run_list.append({
            'ID': act['id'], 'Lauf': act.get('name', 'Lauf'),
            'Datum': datetime.strptime(act['start_date_local'][:10], "%Y-%m-%d").date(),
            'Distanz_km': dist_m / 1000, 'Hoehenmeter': elev_m,
            'Speed_kmh': speed_kmh, 'HR_avg': hr, 'HR_max': act.get('max_heartrate', hr),
            'SPM': spm, 'EF': ef, 'GaEF': gaef
        })
    return pd.DataFrame(run_list)

# --- APP ROUTING ---
if 'access_token' not in st.session_state:
    if 'code' in st.query_params:
        auth_code = st.query_params['code']
        token_data = exchange_token(auth_code)
        if 'access_token' in token_data:
            st.session_state['access_token'] = token_data['access_token']
            st.session_state['athlete_name'] = token_data['athlete']['firstname']
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Login fehlgeschlagen.")
    else:
        st.title("Willkommen bei TAURX 🏃‍♂️")
        st.markdown("Verknüpfe dein Strava-Konto, um auf das GaEF-Dashboard zuzugreifen.")
        st.link_button("Mit Strava verbinden", get_login_url(), type="primary")

else:
    # --- AB HIER IST DER NUTZER EINGELOGGT ---
    st.sidebar.success(f"Eingeloggt als {st.session_state['athlete_name']}")
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

    df_runs = load_all_runs(st.session_state['access_token'])
    
    if df_runs.empty:
        st.warning("Es wurden keine Laufdaten mit Herzfrequenz gefunden.")
        st.stop()

    st.sidebar.title("TAURX Navigation")
    app_mode = st.sidebar.radio("Modul wählen:", ["📅 Weekly GaEF", "🔬 Intra-Run Analyse", "🧮 Korrelationen", "📍 Strecken-Vergleich"])
    st.sidebar.markdown("---")

    # ==========================================
    # MODUL 1: WEEKLY GAEF
    # ==========================================
    if app_mode == "📅 Weekly GaEF":
        st.title("📊 Aerobes Leistungs-Radar")
        min_date, max_date = df_runs['Datum'].min(), df_runs['Datum'].max()
        start_date = st.sidebar.date_input("Startdatum", min_date, min_value=min_date, max_value=max_date)
        end_date = st.sidebar.date_input("Enddatum", max_date, min_value=min_date, max_value=max_date)
        min_dist_filter = st.sidebar.slider("Mindestdistanz (km):", 0.0, 50.0, 10.0, 0.5)
        
        mask = (df_runs['Datum'] >= start_date) & (df_runs['Datum'] <= end_date) & (df_runs['Distanz_km'] >= min_dist_filter)
        df_filtered = df_runs.loc[mask].copy()
        
        if not df_filtered.empty:
            df_filtered['Jahr_Woche'] = df_filtered['Datum'].apply(lambda x: f"{x.isocalendar()[0]}-W{x.isocalendar()[1]:02d}")
            df_weekly = df_filtered.groupby('Jahr_Woche').agg(
                Woechentliche_Distanz=('Distanz_km', 'sum'), Woechentliche_Hoehe=('Hoehenmeter', 'sum'),
                Schnitt_EF=('EF', 'mean'), Schnitt_GaEF=('GaEF', 'mean'), Anzahl_Laeufe=('Datum', 'count')
            ).reset_index().sort_values('Jahr_Woche')
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Analysierte Läufe", len(df_filtered))
            c2.metric("Gesamtdistanz", f"{df_filtered['Distanz_km'].sum():.1f} km")
            c3.metric("Ø-EF (Flach)", f"{df_filtered['EF'].mean():.2f}")
            c4.metric("Ø-GaEF (Höhe)", f"{df_filtered['GaEF'].mean():.2f}")
            
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=df_weekly['Jahr_Woche'], y=df_weekly['Woechentliche_Distanz'], name="Volumen (km)", marker_color="rgba(160,160,160,0.3)"), secondary_y=True)
            fig.add_trace(go.Scatter(x=df_weekly['Jahr_Woche'], y=df_weekly['Schnitt_EF'], name="EF", mode="lines+markers", line=dict(color="#1f77b4", width=3)), secondary_y=False)
            fig.add_trace(go.Scatter(x=df_weekly['Jahr_Woche'], y=df_weekly['Schnitt_GaEF'], name="GaEF", mode="lines+markers", line=dict(color="#ff7f0e", width=3)), secondary_y=False)
            fig.update_layout(height=500, hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Keine Daten für diese Filter.")

    # ==========================================
    # MODUL 2: INTRA-RUN
    # ==========================================
    elif app_mode == "🔬 Intra-Run Analyse":
        st.title("🔬 Intra-Run GaEF Analyse")
        run_options = {f"{r['Datum'].strftime('%d.%m.%Y')} - {r['Lauf']} ({r['Distanz_km']:.1f} km)": r['ID'] for _, r in df_runs.iterrows()}
        selected_act_id = run_options[st.sidebar.selectbox("Lauf wählen:", list(run_options.keys()))]
        split_km = st.sidebar.select_slider("Segment-Länge:", options=[0.1,0.25,0.5, 1.0, 2.0, 5.0, 6.706, 10.0], value=1.0)
        
        @st.cache_data(show_spinner="Lade Streams...")
        def get_streams(act_id, token):
            # UPDATE: 'cadence' zu den angeforderten Schlüsseln hinzugefügt
            res = requests.get(
                f"https://www.strava.com/api/v3/activities/{act_id}/streams", 
                headers={'Authorization': f"Bearer {token}"}, 
                params={'keys': 'distance,time,altitude,heartrate,moving,cadence', 'key_by_type': 'true'}
            )
            return res.json() if res.status_code == 200 else None
            
        streams = get_streams(selected_act_id, st.session_state['access_token'])
        
        if streams and 'heartrate' in streams:
            dist_data = streams['distance']['data']
            time_data = streams['time']['data']
            alt_data = streams['altitude']['data']
            hr_data = streams['heartrate']['data']
            moving_data = streams['moving']['data']
            
            # Prüfen, ob die Uhr Trittfrequenz-Daten aufgezeichnet hat
            has_cadence = 'cadence' in streams
            cadence_data = streams['cadence']['data'] if has_cadence else []
            
            splits = []
            target_m = split_km * 1000
            start_idx = 0
            
            for i, d in enumerate(dist_data):
                if d >= target_m or i == len(dist_data) - 1:
                    mov_time = sum(time_data[k] - time_data[k-1] for k in range(start_idx + 1, i + 1) if moving_data[k])
                    if mov_time > 0:
                        seg_hr = [hr_data[k] for k in range(start_idx, i+1) if moving_data[k]]
                        avg_hr = np.mean(seg_hr) if seg_hr else 0
                        elev = sum(alt_data[k] - alt_data[k-1] for k in range(start_idx + 1, i + 1) if alt_data[k] > alt_data[k-1] and moving_data[k])
                        seg_dist = dist_data[i] - dist_data[start_idx]
                        
                        # Durchschnittliche SPM (Schritte pro Minute) berechnen. Strava liefert Umdrehungen, daher * 2
                        avg_spm = None
                        if has_cadence:
                            seg_cad = [cadence_data[k] for k in range(start_idx, i+1) if moving_data[k] and cadence_data[k] > 0]
                            if seg_cad:
                                avg_spm = np.mean(seg_cad) * 2
                        
                        if avg_hr > 0:
                            splits.append({
                                'KM': target_m / 1000, 
                                'EF': (seg_dist / (mov_time / 60)) / avg_hr,
                                'GaEF': ((seg_dist + elev * 10) / (mov_time / 60)) / avg_hr, 
                                'HR': avg_hr,
                                'Elev': elev,
                                'SPM': avg_spm
                            })
                    start_idx = i
                    target_m += split_km * 1000
                    
            if splits:
                df_splits = pd.DataFrame(splits)
                
                # GRAFIK 1: Effizienz
                st.markdown("### Effizienz & Herzfrequenz")
                fig1 = make_subplots(specs=[[{"secondary_y": True}]])
                fig1.add_trace(go.Scatter(x=df_splits['KM'], y=df_splits['EF'], name="EF (Flach)", line=dict(color="#1f77b4", dash='dot')), secondary_y=False)
                fig1.add_trace(go.Scatter(x=df_splits['KM'], y=df_splits['GaEF'], name="GaEF (Höhenbereinigt)", line=dict(color="#ff7f0e", width=4)), secondary_y=False)
                fig1.add_trace(go.Scatter(x=df_splits['KM'], y=df_splits['HR'], name="HR", line=dict(color="rgba(214, 39, 40, 0.4)")), secondary_y=True)
                fig1.update_layout(height=400, hovermode="x unified", margin=dict(b=10))
                st.plotly_chart(fig1, use_container_width=True)
                
                # GRAFIK 2: SPM vs Höhenmeter
                if has_cadence and not df_splits['SPM'].isnull().all():
                    st.markdown("### Schrittfrequenz vs. Höhenmeter")
                    fig2 = make_subplots(specs=[[{"secondary_y": True}]])
                    # Balken für Höhenmeter im Hintergrund (sekundäre Achse)
                    fig2.add_trace(go.Bar(x=df_splits['KM'], y=df_splits['Elev'], name="Höhenmeter (+)", marker_color="rgba(160,160,160,0.4)"), secondary_y=True)
                    # Linie für SPM (primäre Achse)
                    fig2.add_trace(go.Scatter(x=df_splits['KM'], y=df_splits['SPM'], name="SPM", mode='lines+markers', line=dict(color="#2ca02c", width=3)), secondary_y=False)
                    
                    fig2.update_layout(
                        height=350, 
                        hovermode="x unified",
                        yaxis=dict(title="SPM (Schritte/Min)", range=[df_splits['SPM'].min() * 0.95, df_splits['SPM'].max() * 1.05]),
                        yaxis2=dict(title="Höhenmeter (m)", showgrid=False, range=[0, df_splits['Elev'].max() * 2]) # *2 damit die Balken nur in der unteren Hälfte bleiben
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("Für diesen Lauf wurden leider keine Schrittfrequenz-Daten aufgezeichnet.")

            else:
                st.warning("Keine Segmente berechenbar.")
        else:
            st.warning("Keine Pulswerte für diesen Lauf.")
    # ==========================================
    # MODUL 3: KORRELATIONEN
    # ==========================================
    elif app_mode == "🧮 Korrelationen":
        st.title("🔗 Metrik-Korrelationen")
        min_dist = st.sidebar.slider("Mindestdistanz (km)", 0.0, 40.0, 5.0, 1.0)
        df_corr = df_runs[df_runs['Distanz_km'] >= min_dist].drop(columns=['ID', 'Lauf', 'Datum']).dropna()
        
        if not df_corr.empty:
            fig_hm = px.imshow(df_corr.corr(), text_auto=".2f", aspect="auto", color_continuous_scale="RdBu_r", zmin=-1, zmax=1)
            st.plotly_chart(fig_hm, use_container_width=True)
            
            st.markdown("### 🎯 Multivariate Detail-Analyse")
            cols = df_corr.columns.tolist()
            c1, c2, c3 = st.columns(3)
            x_ax = c1.selectbox("X-Achse:", cols, index=cols.index('SPM') if 'SPM' in cols else 0)
            y_ax = c2.selectbox("Y-Achse:", cols, index=cols.index('HR_avg') if 'HR_avg' in cols else 0)
            c_ax = c3.selectbox("Einfärben:", cols, index=cols.index('Hoehenmeter') if 'Hoehenmeter' in cols else 0)
            
            fig_sc = px.scatter(df_runs[df_runs['Distanz_km'] >= min_dist], x=x_ax, y=y_ax, color=c_ax, hover_data=['Lauf', 'Datum', 'Distanz_km'], color_continuous_scale="Viridis")
            fig_sc.update_traces(marker=dict(size=10, line=dict(width=1, color='DarkSlateGrey')))
            st.plotly_chart(fig_sc, use_container_width=True)

    # ==========================================
    # MODUL 4: STRECKEN-VERGLEICH (Ähnliche Läufe)
    # ==========================================
    elif app_mode == "📍 Strecken-Vergleich":
        st.title("📍 Modul 4: Strecken-Vergleich")
        st.markdown("Vergleiche deine Effizienz auf einer spezifischen Standard-Runde über die Zeit.")

        # 1. Referenz-Lauf auswählen
        run_options = df_runs.apply(lambda row: f"{row['Datum'].strftime('%Y-%m-%d')} - {row['Lauf']} ({row['Distanz_km']:.1f} km)", axis=1).tolist()
        
        selected_run_str = st.selectbox("Wähle einen Referenz-Lauf (deine 'Standard-Runde'):", options=run_options)

        # 2. Werte des gewählten Laufs extrahieren
        selected_idx = run_options.index(selected_run_str)
        ref_run = df_runs.iloc[selected_idx]

        ref_dist = ref_run['Distanz_km']
        ref_elev = ref_run['Hoehenmeter']

        # 3. Schieberegler für die Toleranzen
        col1, col2 = st.columns(2)
        with col1:
            dist_tol = st.slider("Distanz-Toleranz (+/- %)", min_value=1.0, max_value=20.0, value=5.0, step=1.0)
        with col2:
            elev_tol = st.slider("Höhenmeter-Toleranz (+/- %)", min_value=1.0, max_value=50.0, value=5.0, step=1.0)

        # 4. Mathematische Grenzen berechnen
        dist_min = ref_dist * (1 - dist_tol/100)
        dist_max = ref_dist * (1 + dist_tol/100)

        if ref_elev > 0:
            elev_min = ref_elev * (1 - elev_tol/100)
            elev_max = ref_elev * (1 + elev_tol/100)
        else:
            elev_min = 0
            elev_max = 5

        # 5. Alle Läufe filtern, die in dieses Raster fallen
        similar_runs = df_runs[
            (df_runs['Distanz_km'] >= dist_min) & (df_runs['Distanz_km'] <= dist_max) &
            (df_runs['Hoehenmeter'] >= elev_min) & (df_runs['Hoehenmeter'] <= elev_max)
        ].copy()

        # 6. Ergebnisse anzeigen und Plotten
        st.write(f"**{len(similar_runs)} ähnliche Läufe gefunden** (Referenz: ~{ref_dist:.1f} km, ~{ref_elev:.0f} HM)")

        if len(similar_runs) > 1:
            similar_runs = similar_runs.sort_values(by='Datum')

            fig4 = px.line(
                similar_runs,
                x='Datum',
                y='GaEF',
                markers=True,
                title="Entwicklung deines GaEF auf dieser Strecke",
                labels={'Datum': 'Datum', 'GaEF': 'Gravity-adjusted EF'},
                hover_data=['Lauf', 'Distanz_km', 'Hoehenmeter', 'HR_avg', 'Speed_kmh']
            )
            
            fig4.update_traces(line_color='#FF4B4B', marker=dict(size=10))
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("Nicht genug ähnliche Läufe gefunden, um einen Trend zu zeichnen. Erhöhe gegebenenfalls die Toleranzen oben in den Schiebereglern.")