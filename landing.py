import streamlit as st

# Configurar página
st.set_page_config(
    page_title="CAUMAX - Análisis Hidrológico", 
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Si va a mostrar suscripción → mostrar UI de Stripe integrada
if st.session_state.get("show_subscription", False):
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
    
    st.stop()

# Si ya está autenticado → redireccionar a app.py en puerto separado
if st.session_state.get("authenticated", False):
    st.markdown("### 🚀 Accediendo a tu aplicación...")
    st.markdown("**Redirigiendo a CAUMAX App...**")
    
    # Detectar si estamos en desarrollo o deployment
    import os
    
    # En GitHub deployment, usar la URL de tu repositorio
    # En desarrollo local, usar localhost
    if os.getenv('REPLIT_DOMAINS'):
        # Estamos en Replit deployment
        app_url = f"https://{os.getenv('REPLIT_DOMAINS').split(',')[0]}"
    elif os.getenv('GITHUB_REPOSITORY'):
        # Estamos en GitHub deployment - reemplaza con tu URL real
        app_url = "https://tu-usuario.github.io/caumax-app"  # CAMBIAR POR TU URL REAL
    else:
        # Desarrollo local
        app_url = "http://localhost:5001"
    
    # JavaScript redirect automático
    st.markdown(f"""
    <script>
    setTimeout(function() {{
        window.location.href = "{app_url}";
    }}, 2000);
    </script>
    """, unsafe_allow_html=True)
    
    # Enlace manual por si no funciona JS
    st.markdown(f"**[👉 Abrir CAUMAX App manualmente]({app_url})**")
    st.markdown("_Redirección automática en 2 segundos..._")
    st.stop()

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
                # Usuario válido → EJECUTAR APP.PY INMEDIATAMENTE
                st.session_state.user_email = user_email
                st.session_state.subscription_status = status
                st.session_state.authenticated = True
                st.rerun()
                
            else:
                # Usuario sin suscripción activa
                st.error("❌ No encontramos una suscripción activa para este email")
                st.info("💡 Si ya pagaste, puede tomar unos minutos en activarse")
        
        elif access_submitted and not user_email:
            st.warning("⚠️ Por favor introduce tu email")