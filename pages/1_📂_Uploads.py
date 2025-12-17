import streamlit as st
from src import storage

st.set_page_config(page_title="Uploads", layout="wide")
st.title("☁️ Central de Arquivos")
st.info("Arquivos salvos aqui ficam seguros na nuvem. Não precisa reenviar ao trocar de aba.")

col1, col2 = st.columns(2)

def upload_box(emp, col):
    with col:
        st.subheader(emp)
        # Full
        f1 = st.file_uploader(f"Full (ML) - {emp}", key=f"u1_{emp}")
        if f1:
            if storage.upload(f1, f"{emp}/FULL.xlsx"): st.success("✅ Full Salvo")
        
        # Ext
        f2 = st.file_uploader(f"Ext (Shopee) - {emp}", key=f"u2_{emp}")
        if f2:
            if storage.upload(f2, f"{emp}/EXT.xlsx"): st.success("✅ Ext Salvo")
            
        # Fisico
        f3 = st.file_uploader(f"Físico - {emp}", key=f"u3_{emp}")
        if f3:
            if storage.upload(f3, f"{emp}/FISICO.xlsx"): st.success("✅ Físico Salvo")

        st.caption("Status Nuvem:")
        st.write(f"Full: {'✅' if storage.download(f'{emp}/FULL.xlsx') else '❌'}")
        st.write(f"Ext: {'✅' if storage.download(f'{emp}/EXT.xlsx') else '❌'}")
        st.write(f"Físico: {'✅' if storage.download(f'{emp}/FISICO.xlsx') else '❌'}")

upload_box("ALIVVIA", col1)
upload_box("JCA", col2)