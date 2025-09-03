import streamlit as st
import stripe
import os
from datetime import datetime, timedelta
from subscription_manager import SubscriptionManager

# Usuarios de prueba ficticios
TEST_USERS = {
    "usuario1@test.com": {
        "name": "Ana Hidróloga",
        "status": "active",
        "subscription_id": "sub_test_12345",
        "current_period_end": datetime.now() + timedelta(days=300),
        "description": "Usuario activo con suscripción válida"
    },
    "usuario2@test.com": {
        "name": "Carlos Ingeniero",
        "status": "active",  # CAMBIADO a activo ya que tiene suscripción real en Stripe
        "subscription_id": "sub_real_stripe",
        "current_period_end": datetime.now() + timedelta(days=365),
        "description": "Usuario con suscripción activa (verificada en Stripe)"
    },
    "admin@test.com": {
        "name": "Administrador",
        "status": "admin",
        "subscription_id": "admin_access",
        "current_period_end": datetime.now() + timedelta(days=9999),
        "description": "Usuario administrador con acceso completo"
    },
    "nuevo@test.com": {
        "name": "Usuario Nuevo",
        "status": "new",
        "subscription_id": None,
        "current_period_end": None,
        "description": "Usuario completamente nuevo"
    },
    "vencido@test.com": {
        "name": "Suscripción Vencida",
        "status": "expired",
        "subscription_id": "sub_expired_67890",
        "current_period_end": datetime.now() - timedelta(days=30),
        "description": "Usuario con suscripción vencida"
    }
}

def create_test_mode_manager():
    """Crear un SubscriptionManager en modo de prueba"""
    
    class TestSubscriptionManager(SubscriptionManager):
        def __init__(self):
            super().__init__()
            self.test_mode = True
            # Usar el mismo producto real para pruebas
            self.product_id = "prod_Sys0oqoPo4gez4"  # Tu Product ID real
            self.price_id = "price_1S2uGhRoxsFOnt6irCnbfGrJ"  # Price ID de 50€/año
            
        def check_subscription_status(self, customer_email):
            """Override para usar datos de prueba PERO consultar Stripe real"""
            # Primero consultar Stripe real para ver si tiene suscripción activa
            try:
                st.info(f"🔍 Consultando Stripe para {customer_email}...")
                real_status = super().check_subscription_status(customer_email)
                st.info(f"📊 Resultado Stripe: {real_status}")
                if real_status.get("active"):
                    st.success(f"🎯 Usuario {customer_email} tiene suscripción REAL activa en Stripe")
                    return real_status
                else:
                    st.warning(f"❌ Usuario {customer_email} no tiene suscripción activa en Stripe")
            except Exception as e:
                st.error(f"🚫 Error consultando Stripe: {e}")
                import traceback
                st.code(traceback.format_exc())
            
            # Si no hay suscripción real, usar datos de prueba
            if customer_email in TEST_USERS:
                user_data = TEST_USERS[customer_email]
                
                if user_data["status"] == "active":
                    st.info(f"🧪 Usuario {customer_email} usando datos de prueba: ACTIVA")
                    return {
                        "status": "active",
                        "active": True,
                        "customer_id": f"cus_test_{customer_email.split('@')[0]}",
                        "subscription_id": user_data["subscription_id"],
                        "current_period_end": user_data["current_period_end"],
                        "cancel_at_period_end": False
                    }
                elif user_data["status"] == "admin":
                    return {
                        "status": "active", 
                        "active": True,
                        "customer_id": "cus_admin_test",
                        "subscription_id": user_data["subscription_id"],
                        "current_period_end": user_data["current_period_end"],
                        "cancel_at_period_end": False
                    }
                elif user_data["status"] == "expired":
                    return {
                        "status": "inactive",
                        "active": False,
                        "customer_id": f"cus_test_{customer_email.split('@')[0]}",
                        "subscription_id": user_data["subscription_id"],
                        "current_period_end": user_data["current_period_end"],
                        "cancel_at_period_end": False
                    }
                else:  # inactive or new
                    st.info(f"🧪 Usuario {customer_email} usando datos de prueba: {user_data['status'].upper()}")
                    return {
                        "status": "no_customer" if user_data["status"] == "new" else "inactive",
                        "active": False
                    }
            else:
                # Usuario no en la lista de prueba
                return {"status": "no_customer", "active": False}
        
        def create_checkout_session(self, customer_email, success_url, cancel_url):
            """Override para crear sesión de prueba REAL de Stripe"""
            try:
                st.info("🧪 **MODO PRUEBA**: Usando Stripe Test Mode")
                
                # En modo prueba, crear una sesión REAL de Stripe usando las claves reales pero en test mode
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
                
                # Crear sesión REAL de Stripe Checkout
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
                st.error(f"Error en modo prueba: {str(e)}")
                return None
    
    return TestSubscriptionManager()

def show_test_users_selector():
    """Mostrar selector de usuarios de prueba"""
    st.sidebar.markdown("---")
    st.sidebar.subheader("🧪 Usuarios de Prueba")
    
    # Crear dropdown con usuarios de prueba
    user_options = {
        "Seleccionar usuario...": "",
        "👩‍🔬 Ana (Activa)": "usuario1@test.com", 
        "👨‍💻 Carlos (Sin suscripción)": "usuario2@test.com",
        "👤 Admin (Administrador)": "admin@test.com",
        "🆕 Nuevo Usuario": "nuevo@test.com",
        "⏰ Suscripción Vencida": "vencido@test.com"
    }
    
    selected = st.sidebar.selectbox(
        "Cambiar usuario:",
        options=list(user_options.keys())
    )
    
    if selected != "Seleccionar usuario..." and user_options[selected]:
        email = user_options[selected]
        user_info = TEST_USERS[email]
        
        # Actualizar session state
        st.session_state.user_email = email
        
        # Mostrar info del usuario seleccionado
        st.sidebar.success(f"✅ Usuario: {user_info['name']}")
        st.sidebar.caption(f"📧 {email}")
        st.sidebar.caption(f"ℹ️ {user_info['description']}")
        
        return email
    
    return st.session_state.get("user_email", "")

def show_stripe_test_cards():
    """Mostrar información sobre tarjetas de prueba de Stripe"""
    st.sidebar.markdown("---")
    st.sidebar.subheader("💳 Tarjetas de Prueba Stripe")
    
    with st.sidebar.expander("Ver tarjetas de prueba"):
        st.markdown("""
        **Tarjeta de éxito:**
        - Número: `4242 4242 4242 4242`
        - Fecha: Cualquier fecha futura
        - CVC: Cualquier 3 dígitos
        
        **Tarjeta que falla:**
        - Número: `4000 0000 0000 0002`
        - Causa: Declinada por insuficientes fondos
        
        **Tarjeta 3D Secure:**
        - Número: `4000 0027 6000 3184`
        - Requiere autenticación adicional
        """)

# Función para integrar en la app principal
def enable_test_mode():
    """Activar modo de prueba en la aplicación"""
    st.session_state.test_mode = True
    st.sidebar.success("🧪 **MODO PRUEBA ACTIVADO**")
    st.sidebar.caption("Usando usuarios ficticios y Stripe Test Mode")
    
def is_test_mode():
    """Verificar si estamos en modo prueba"""
    return st.session_state.get("test_mode", False)