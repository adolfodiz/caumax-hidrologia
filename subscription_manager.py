import streamlit as st
import streamlit.components.v1 as components
import stripe
import os
from datetime import datetime, timedelta

# Configurar Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

class SubscriptionManager:
    def __init__(self):
        self.annual_price_eur = 50.00
        # Usar el Product ID existente en lugar de crear productos nuevos
        self.product_id = "prod_Sys0oqoPo4gez4"  # Tu Product ID de CAUMAX
        self.price_id = "price_1S2uGhRoxsFOnt6irCnbfGrJ"  # Price ID de 50€/año
        
    def create_customer(self, email, name=None):
        """Crear un cliente en Stripe"""
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name or "Usuario",
                metadata={
                    "app": "hydrological_analysis",
                    "created_at": str(datetime.now())
                }
            )
            return customer
        except Exception as e:
            st.error(f"Error creando cliente: {str(e)}")
            return None
    
    def create_subscription(self, customer_id, price_id):
        """Crear suscripción anual"""
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"],
            )
            return subscription
        except Exception as e:
            st.error(f"Error creando suscripción: {str(e)}")
            return None
    
    def check_subscription_status(self, customer_email):
        """Verificar estado de suscripción de un cliente"""
        try:
            # Buscar cliente por email
            customers = stripe.Customer.list(email=customer_email)
            if not customers.data:
                return {"status": "no_customer", "active": False}
            
            customer = customers.data[0]
            
            # Buscar suscripciones activas
            subscriptions = stripe.Subscription.list(
                customer=customer.id,
                status="active"
            )
            
            st.info(f"📋 DEBUG: Suscripciones activas: {len(subscriptions.data)}")
            
            # AGREGAR: Ver todas las suscripciones (cualquier estado)
            all_subs = stripe.Subscription.list(customer=customer.id)
            st.info(f"📋 DEBUG: Total suscripciones: {len(all_subs.data)}")
            for sub in all_subs.data:
                st.info(f"  - Suscripción {sub.id}: Estado = {sub.status}")
                    
            
            if subscriptions.data:
                subscription = subscriptions.data[0]
                return {
                    "status": "active", 
                    "active": True,
                    "customer_id": customer.id,
                    "subscription_id": subscription.id,
                    "current_period_end": datetime.fromtimestamp(subscription.get('current_period_end', 0)),
                    "cancel_at_period_end": subscription.get('cancel_at_period_end', False)
                }
            else:
                return {"status": "inactive", "active": False, "customer_id": customer.id}
                
        except Exception as e:
            st.error(f"Error verificando suscripción: {str(e)}")
            return {"status": "error", "active": False}
    
    def create_checkout_session(self, customer_email, success_url, cancel_url):
        """Crear sesión de pago para suscripción"""
        try:
            # Buscar o crear precio usando el Product ID existente
            if not self.price_id:
                # Primero buscar si ya existe un precio para este producto
                prices = stripe.Price.list(product=self.product_id, active=True)
                
                if prices.data:
                    # Usar el primer precio activo encontrado
                    self.price_id = prices.data[0].id
                    st.info(f"🔄 Usando precio existente: {self.price_id}")
                else:
                    # Crear nuevo precio para el producto existente
                    price = stripe.Price.create(
                        unit_amount=int(self.annual_price_eur * 100),
                        currency="eur",
                        recurring={"interval": "year"},
                        product=self.product_id,  # Usar producto existente
                    )
                    self.price_id = price.id
                    st.success(f"✅ Precio creado: {self.price_id}")
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price": self.price_id,
                    "quantity": 1,
                }],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=customer_email,
                locale="es",
            )
            return checkout_session
            
        except Exception as e:
            st.error(f"Error creando sesión de pago: {str(e)}")
            return None

def show_active_user_header(email, status):
    """Mostrar header compacto para usuario activo"""
    # Mostrar info del usuario en el área principal, no en sidebar
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Obtener nombre del usuario si está disponible
        user_name = email.split('@')[0].title()
        if hasattr(status, 'get') and status.get('customer_name'):
            user_name = status['customer_name']
        
        st.success(f"✅ **{user_name}** - Suscripción Activa")
    
    with col2:
        # Calcular fecha de vencimiento directamente
        future_date = datetime.now() + timedelta(days=365)
        st.info(f"📅 Válida hasta: {future_date.strftime('%d/%m/%Y')}")
    
    # IMPORTANTE: Limpiar completamente la sidebar para usuarios activos
    # No mostrar controles de suscripción
    return  # No continuar con el resto de la UI de suscripción

def show_subscription_ui():
    """Interfaz de usuario para gestión de suscripciones"""
    
    # Inicializar session state
    if "user_email" not in st.session_state:
        st.session_state.user_email = ""
    if "subscription_status" not in st.session_state:
        st.session_state.subscription_status = {"status": "unknown", "active": False}
    
    # Usar manager de prueba si estamos en modo test
    from test_users import is_test_mode, create_test_mode_manager
    if is_test_mode():
        subscription_manager = create_test_mode_manager()
    else:
        subscription_manager = SubscriptionManager()

    # PASO 1: Detectar si ya tenemos usuario activo
    current_email = st.session_state.user_email
    if current_email:
        current_status = st.session_state.subscription_status
        if current_status.get("status") == "active":
            # Usuario ACTIVO -> Solo mostrar header, NO sidebar de suscripción
            show_active_user_header(current_email, current_status)
            return True  # Usuario tiene acceso - NO mostrar más controles
    
    # PASO 2: Si no hay usuario activo, mostrar controles completos
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔐 Gestión de Suscripción")
    
    # Input de email
    email = st.sidebar.text_input(
        "Email:", 
        value=st.session_state.user_email,
        placeholder="tu@email.com",
        key="subscription_email_input"
    )
    
    if email and email != st.session_state.user_email:
        st.session_state.user_email = email
        st.session_state.subscription_status = subscription_manager.check_subscription_status(email)
        st.rerun()
    
    # Verificación especial para Carlos
    if email == "usuario2@test.com" and st.session_state.subscription_status.get("status") != "active":
        st.sidebar.info("🔄 Verificando suscripción real de Carlos...")
        st.session_state.subscription_status = subscription_manager.check_subscription_status(email)
        if st.session_state.subscription_status.get("active"):
            st.rerun()
    
    # Mostrar estado de suscripción
    if email:
        status = st.session_state.subscription_status
        
        if status["status"] == "active":
            # Si detectamos usuario activo aquí, rerun para mostrar vista limpia
            st.rerun()
            
        elif status["status"] == "inactive":
            st.sidebar.warning("⚠️ Suscripción Inactiva")
            
        elif status["status"] == "no_customer":
            st.sidebar.info("ℹ️ Usuario Nuevo")
        
        # Botón para suscribirse o renovar
        if st.sidebar.button("💳 Suscribirse (€50/año)", use_container_width=True):
            try:
                # Obtener URL base actual - compatible con Replit y deployment
                repl_slug = os.getenv("REPL_SLUG") 
                repl_owner = os.getenv("REPL_OWNER")
                replit_url = os.getenv("REPLIT_URL")
                
                # Probar diferentes formas de obtener la URL de Replit
                if replit_url:
                    base_url = replit_url
                elif repl_slug and repl_owner:
                    base_url = f"https://{repl_slug}.{repl_owner}.repl.co"
                else:
                    # Para testing local, usar localhost pero indicar que necesita URL real para producción
                    base_url = "http://localhost:5000"
                    st.warning("⚠️ URL de retorno temporal - actualizar para producción")
                
                checkout_session = subscription_manager.create_checkout_session(
                    customer_email=email,
                    success_url=f"{base_url}/?subscription=success",
                    cancel_url=f"{base_url}/?subscription=cancelled"
                )
                
                if checkout_session:
                    # Mostrar información y enlace directo para abrir Stripe Checkout
                    st.success(f"✅ Sesión de pago creada exitosamente!")
                    st.info(f"🆔 Sesión ID: {checkout_session.id}")
                    
                    # Usar la URL correcta que proporciona Stripe (no construir manualmente)
                    checkout_url = checkout_session.url if hasattr(checkout_session, 'url') else f"https://checkout.stripe.com/c/pay/{checkout_session.id}"
                    
                    st.markdown(f"""
                    ### 💳 Proceder al pago
                    
                    **Haz click en el enlace de abajo para completar tu suscripción:**
                    
                    🔗 [**ABRIR STRIPE CHECKOUT**]({checkout_url})
                    
                    *Se abrirá en una nueva pestaña. Después del pago exitoso, regresarás automáticamente.*
                    """)
                    
                    # JavaScript alternativo como respaldo
                    js_code = f"""
                    <script src="https://js.stripe.com/v3/"></script>
                    <script>
                        setTimeout(function() {{
                            const stripe = Stripe('{STRIPE_PUBLISHABLE_KEY}');
                            stripe.redirectToCheckout({{
                                sessionId: '{checkout_session.id}'
                            }}).then(function (result) {{
                                if (result.error) {{
                                    alert('Error: ' + result.error.message);
                                }}
                            }});
                        }}, 2000);
                    </script>
                    """
                    components.html(js_code, height=50)
                    
            except Exception as e:
                st.sidebar.error(f"Error iniciando pago: {str(e)}")
    
    else:
        st.sidebar.write("Introduce tu email para verificar suscripción")
    
    return False  # Usuario no tiene acceso

def check_access():
    """Verificar si el usuario tiene acceso a la aplicación"""
    # Email del administrador (acceso completo siempre) 
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@caumax.com")
    
    if st.session_state.get("user_email") == ADMIN_EMAIL:
        return True
    
    # Verificar parámetros URL para éxito/cancelación de pago
    query_params = st.query_params
    if "subscription" in query_params:
        if query_params["subscription"] == "success":
            st.success("¡Pago procesado exitosamente! Tu suscripción está activa.")
        elif query_params["subscription"] == "cancelled":
            st.warning("Pago cancelado. Puedes intentarlo de nuevo cuando gustes.")
    
    return show_subscription_ui()
