import streamlit as st
import requests
import urllib3
from bs4 import BeautifulSoup
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# Konfigurasi Halaman
st.set_page_config(page_title="Auto KRS Sniper Mode", layout="wide")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CSS CUSTOM ---
# Menyembunyikan elemen standar agar lebih bersih saat mode sniper
st.markdown("""
    <style>
    .stAlert { padding: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- CORE FUNCTIONS ---

def request_with_retry(url, method="GET", data=None, cookie_str="", retry_wait=0.01):
    headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"}
    # Loop request level rendah (untuk koneksi error/timeout)
    while True:
        try:
            if method == "POST":
                return requests.post(url, headers=headers, data=data, verify=False, timeout=3)
            return requests.get(url, headers=headers, verify=False, timeout=3)
        except:
            time.sleep(retry_wait)

def get_auth_token(cookie_str):
    """Stage 1: Mendapatkan MX dan IDX"""
    try:
        res = request_with_retry("https://siakad.uin-malang.ac.id/2.0/uin-krs", cookie_str=cookie_str)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            mx_el = soup.find('input', {'id': 'mx'})
            idx_el = soup.find('input', {'id': 'idx'})
            if mx_el and idx_el:
                return mx_el['value'], idx_el['value']
    except:
        pass
    return None, None

def get_course_ids_sniper_mode(jadwals, idx_value, cookie_str, log_placeholder, status_text):
    """Stage 2: Sniper Mode (Infinite Loop sampai dapat)"""
    cached_ids = {}
    attempt = 0
    
    # UI Feedback awal
    log_placeholder.info(f"🎯 SNIPER MODE AKTIF: Mencari ID untuk {len(jadwals)} mata kuliah...")
    
    # INFINITE LOOP (Sampai semua matkul ketemu)
    while len(cached_ids) < len(jadwals):
        attempt += 1
        
        try:
            # Request ke server
            response = request_with_retry(
                "https://siakad.uin-malang.ac.id/2.0/ajx", 
                method="POST", 
                data={'vw_mk': idx_value}, 
                cookie_str=cookie_str
            )
            
            # Jika Server OK (200), kita parsing
            if response.status_code == 200:
                srv_soup = BeautifulSoup(response.text, 'html.parser')
                rows = srv_soup.find_all('tr')
                
                # Cek apakah tabel kosong (Server buka tapi belum ada isinya)
                if not rows:
                    status_text.warning(f"⏳ Percobaan #{attempt}: Server UP, tapi daftar matkul kosong...")
                else:
                    # Parsing baris
                    current_found = 0
                    for target in jadwals:
                        t_m, t_h, t_j, t_d = target
                        key = f"{t_m}|{t_d}"
                        
                        if key in cached_ids: 
                            current_found += 1
                            continue
                        
                        for row in rows:
                            cols = row.find_all('td')
                            if len(cols) > 6:
                                srv_matkul = cols[2].get_text(strip=True).replace(" ","")
                                srv_dosen  = cols[4].get_text(strip=True).replace(" ","")
                                srv_hari   = cols[5].get_text(strip=True).replace(" ","")
                                srv_jam    = cols[6].get_text(strip=True).replace(" ","")

                                # Validasi Ketat
                                if (srv_matkul == t_m.replace(" ","") and 
                                    srv_dosen  == t_d.replace(" ","") and
                                    srv_hari   == t_h.replace(" ","") and
                                    srv_jam    == t_j.replace(" ","")):
                                    
                                    a_tag = row.find('a', id=True)
                                    if a_tag:
                                        cached_ids[key] = a_tag['id']
                                        # Tampilkan log permanen jika ketemu
                                        st.toast(f"✅ Ditemukan: {t_m}", icon="🔥")
                                        break
                    
                    # Update Status Baris (Realtime, tidak spam log)
                    msg = f"⏳ Percobaan #{attempt}: Ditemukan {len(cached_ids)}/{len(jadwals)} Matkul..."
                    if len(cached_ids) < len(jadwals):
                        status_text.markdown(f"**Status:** {msg} (Menunggu sisanya...)")
                    
            else:
                # Handle status code selain 200 (misal 500/502/404)
                status_text.error(f"⚠️ Percobaan #{attempt}: Server Error {response.status_code}. Retrying...")

        except Exception as e:
             status_text.error(f"⚠️ Percobaan #{attempt}: Koneksi Error ({str(e)}). Retrying...")
        
        # Jeda sedikit agar CPU server Streamlit tidak meledak (0.5 detik cukup agresif tapi aman)
        if len(cached_ids) < len(jadwals):
            time.sleep(0.5) 
            
    return cached_ids

def war_worker(key, ad_kr, mx_value, cookie_str, status_container):
    """Stage 3: Worker Thread per Matkul"""
    name = key.split('|')[0]
    retry_count = 0
    
    while True: # Loop sampai sukses
        try:
            res = request_with_retry(
                "https://siakad.uin-malang.ac.id/2.0/ajx", 
                method="POST", 
                data={"ad_kr": ad_kr, "mx": mx_value}, 
                cookie_str=cookie_str
            )
            
            toast = BeautifulSoup(res.text, 'html.parser').find('div', class_='toast-body')
            msg = toast.get_text(strip=True) if toast else "No Response"
            retry_count += 1
            
            if "sukses" in msg.lower():
                status_container.success(f"**{name}**: BERHASIL DIAMBIL! 🎉")
                break
            elif "penuh" in msg.lower():
                 status_container.error(f"**{name}**: PENUH! (Coba {retry_count}x)")
            else:
                 status_container.warning(f"**{name}**: {msg} (Coba {retry_count}x)")
            
            time.sleep(0.01) # Jeda sangat pendek untuk spam
        except:
            time.sleep(0.1)

# --- UI LAYOUT ---

st.title("🦅 Auto KRS: Sniper Mode")
st.caption("Bot akan melakukan looping tanpa henti sampai server UP dan jadwal muncul.")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.header("1. Target Operasi")
    cookie_input = st.text_input("Cookie (PHPSESSID)", placeholder="Paste cookie...", type="password")
    
    st.info("Format: Matkul|Hari|Jam|Dosen")
    default_jadwal = "Bahasa Inggris|Senin|07:00-09:30|Dr. Budi\nFisika Dasar|Selasa|09:30-12:00|Prof. Siti"
    jadwal_text = st.text_area("Jadwal Target", value=default_jadwal, height=200)
    
    start_btn = st.button("AKTIFKAN SNIPER 🔥", type="primary")

with col2:
    st.header("2. Live Monitor")
    log_area = st.empty()       # Untuk log statis
    status_text = st.empty()    # Untuk status loop yang berubah-ubah
    war_area = st.container()   # Area perang

# --- MAIN EXECUTION LOGIC ---

if start_btn:
    if not cookie_input or not jadwal_text:
        st.error("Data tidak lengkap!")
    else:
        # Parsing Jadwal
        jadwals = [line.strip().split('|') for line in jadwal_text.split('\n') if line.strip()]
        
        # STAGE 1: AUTH (Looping juga jika gagal di awal)
        log_area.info("🔄 Mencoba Authentikasi...")
        mx, idx = None, None
        
        # Loop auth sederhana sampai cookie valid/server up
        while not mx or not idx:
            mx, idx = get_auth_token(cookie_input)
            if not mx:
                status_text.warning("⚠️ Gagal Auth / Server Down. Mencoba lagi dalam 1 detik...")
                time.sleep(1)
            else:
                status_text.empty()
        
        log_area.success(f"✅ Auth Berhasil! Token didapatkan.")
            
        # STAGE 2: SNIPER MODE (Infinite Loop di dalam fungsi)
        # Fungsi ini tidak akan return sampai semua ID ketemu
        cached_ids = get_course_ids_sniper_mode(jadwals, idx, cookie_input, log_area, status_text)
        
        status_text.success("✅ SEMUA TARGET TERKUNCI! MEMULAI SERANGAN...")
        time.sleep(0.5) # Napas sebentar sebelum switch UI
        
        # STAGE 3: WAR (MULTI-THREADING)
        with war_area:
            st.divider()
            st.subheader(f"⚔️ EXECUTION PHASE")
            
            status_containers = {}
            for key in cached_ids:
                col_status = st.empty()
                status_containers[key] = col_status
            
            with ThreadPoolExecutor(max_workers=len(cached_ids)) as executor:
                futures = []
                for key, ad_kr in cached_ids.items():
                    futures.append(
                        executor.submit(war_worker, key, ad_kr, mx, cookie_input, status_containers[key])
                    )
                for future in futures:
                    future.result()
        
        st.balloons()
        st.success("MISI SELESAI. Silakan cek SIAKAD.")
