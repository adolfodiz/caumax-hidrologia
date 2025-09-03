import streamlit as st
import os
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
import io
import zipfile
import tempfile
from shapely.ops import unary_union
from pathlib import Path
import rasterio

# Cargar variables de entorno
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def main():
    """Aplicación principal unificada: Landing + App completa"""
    
    # NO configurar página aquí - lo hará app.py cuando sea necesario
    
    # Si va a mostrar suscripción → mostrar UI de Stripe integrada
    if st.session_state.get("show_subscription", False):
        show_subscription_flow()
        return
    
    # Si ya está autenticado → mostrar aplicación principal
    if st.session_state.get("authenticated", False):
        show_main_app()
        return
    
    # Por defecto → mostrar landing page
    show_landing_page()

def show_landing_page():
    """Landing page limpia"""
    
    # Header principal
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <h1>💧 CAUMAX - Análisis Hidrológico Profesional</h1>
        <h3>Plataforma integral para delineación de cuencas y análisis DEM de España</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Layout en dos columnas
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 🔧 Características incluidas:")
        st.markdown("""
        ✅ **Delineación automática de cuencas hidrográficas**  
        ✅ **Análisis con DEM de 25m de resolución de toda España**  
        ✅ **Cálculo de parámetros hidrológicos (Método Racional, GEV, TCEV)**  
        ✅ **Visualización GIS interactiva con mapas de OpenStreetMap**  
        ✅ **Generación de perfiles longitudinales del terreno**  
        ✅ **Exportación de resultados en múltiples formatos**  
        ✅ **Acceso a capas GIS profesionales de España**  
        """)
        
        st.markdown("### 🎯 Ideal para:")
        st.markdown("""
        • **Ingenieros civiles e hidráulicos**
        • **Consultoras ambientales**  
        • **Estudios de impacto hidrológico**
        • **Proyectos de infraestructura**
        • **Investigación académica**
        """)
    
    with col2:
        st.markdown("### 💰 Suscripción Profesional")
        st.markdown("**€50 por año** (€4.17/mes)")
        st.markdown("---")
        
        # Botón rojo para suscribirse 
        if st.button("🔴 **SUSCRIBIRSE**", type="primary", use_container_width=True, key="subscribe_button"):
            st.session_state.show_subscription = True
            st.rerun()
        
        st.markdown("---")
        st.markdown("### Si ya eres USUARIO:")
        
        # Formulario de acceso para usuarios existentes
        with st.form("access_form", clear_on_submit=False):
            user_email = st.text_input(
                "📧 Tu email de suscripción:",
                placeholder="tu@email.com",
                help="Introduce el email con el que te suscribiste"
            )
            
            access_submitted = st.form_submit_button(
                "🟢 **ACCEDER A LA APLICACIÓN**", 
                use_container_width=True
            )
            
            if access_submitted and user_email:
                # Verificar suscripción del usuario
                from subscription_manager import SubscriptionManager
                from test_users import is_test_mode, create_test_mode_manager
                
                # Usar manager apropiado
                if is_test_mode():
                    subscription_manager = create_test_mode_manager()
                else:
                    subscription_manager = SubscriptionManager()
                
                # Verificar estado de suscripción
                status = subscription_manager.check_subscription_status(user_email)
                
                if status.get("status") == "active":
                    # Usuario válido → ACTIVAR APLICACIÓN
                    st.session_state.user_email = user_email
                    st.session_state.subscription_status = status
                    st.session_state.authenticated = True
                    st.success(f"✅ Bienvenido de vuelta, {user_email}!")
                    st.rerun()
                else:
                    # Usuario sin suscripción activa
                    st.error("❌ No encontramos una suscripción activa para este email")
                    st.info("💡 Si ya pagaste, puede tomar unos minutos en activarse")
            
            elif access_submitted and not user_email:
                st.warning("⚠️ Por favor introduce tu email")

def show_subscription_flow():
    """Flujo de suscripción integrado"""
    from subscription_manager import show_subscription_ui
    from test_users import enable_test_mode, is_test_mode, show_test_users_selector, show_stripe_test_cards
    
    st.title("💧 CAUMAX - Proceso de Suscripción")
    
    # Activar modo prueba en sidebar
    if st.sidebar.button("🧪 Activar Modo Prueba"):
        enable_test_mode()
        st.rerun()
    
    # Mostrar selector de usuarios de prueba
    if is_test_mode():
        selected_user = show_test_users_selector()
        show_stripe_test_cards()
        if selected_user:
            st.session_state.user_email = selected_user
    
    # Botón volver al landing
    if st.button("← Volver al inicio"):
        st.session_state.show_subscription = False
        st.rerun()
    
    # Mostrar UI de suscripción integrada
    if show_subscription_ui():
        st.session_state.show_subscription = False
        st.session_state.authenticated = True
        st.rerun()

def show_main_app():
    """Ejecutar TU app.py original directamente"""
    
    # Importar y ejecutar tu aplicación original
    import app
    
    # Llamar a main() de tu aplicación
    if hasattr(app, 'main'):
        app.main()
    else:
        # Si no tiene main(), ejecutar todo el módulo
        pass

if __name__ == "__main__":
    main()