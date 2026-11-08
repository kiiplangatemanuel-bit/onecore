from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "OneCore Technologies Ltd"
    app_env: str = "development"
    debug: bool = False
    secret_key: str = Field(default="unsafe-development-key-change-me")
    access_token_expire_minutes: int = Field(default=30, ge=5, le=60)
    trusted_hosts: str = "*"
    force_https: bool = False
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=30)
    login_rate_limit_window_seconds: int = Field(default=60, ge=10, le=3600)
    database_url: str = "sqlite:///./onecore.db"
    # Supabase-managed PostgreSQL is the production system of record. Keep DATABASE_URL
    # for local development and legacy deployments; SUPABASE_DB_URL takes precedence.
    supabase_db_url: str = ""
    database_pool_size: int = Field(default=5, ge=1, le=30)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    portal_redirect_origins: str = ""
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    integration_mpesa_enabled: bool = False
    mpesa_base_url: str = ""
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = ""
    mpesa_passkey: str = ""
    mpesa_transaction_type: str = "CustomerPayBillOnline"
    mpesa_callback_url: str = ""
    mpesa_initiator_name: str = ""
    mpesa_security_credential: str = ""
    mpesa_b2c_result_url: str = ""
    mpesa_b2c_timeout_url: str = ""

    integration_etims_enabled: bool = False
    etims_base_url: str = ""
    etims_client_id: str = ""
    etims_client_secret: str = ""
    etims_device_serial: str = ""

    integration_sha_enabled: bool = False
    sha_base_url: str = ""
    sha_client_id: str = ""
    sha_client_secret: str = ""
    sha_facility_code: str = ""

    integration_bank_enabled: bool = False
    bank_base_url: str = ""
    bank_client_id: str = ""
    bank_client_secret: str = ""

    integration_email_enabled: bool = False
    email_host: str = ""
    email_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_from: str = ""
    email_use_starttls: bool = True
    public_site_url: str = ""

    integration_sms_enabled: bool = False
    sms_base_url: str = ""
    sms_api_key: str = ""
    sms_sender_id: str = ""

    integration_whatsapp_enabled: bool = False
    whatsapp_base_url: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""

    crm_public_base_url: str = ""
    crm_delivery_callback_secret: str = ""
    healthcare_phi_encryption_key: str = ""

    integration_ai_enabled: bool = False
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    integration_ai_fallback_enabled: bool = False
    ai_fallback_base_url: str = ""
    ai_fallback_api_key: str = ""
    ai_fallback_model: str = ""

    integration_object_storage_enabled: bool = False
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = ""
    s3_region: str = ""


    @property
    def database_connection_url(self) -> str:
        return (self.supabase_db_url or self.database_url).strip()

    @model_validator(mode="after")
    def validate_production_security(self):
        production = self.app_env.strip().lower() in {"production", "prod"}
        if production:
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if self.secret_key == "unsafe-development-key-change-me" or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be a unique random value of at least 32 characters in production")
            from sqlalchemy.engine import make_url
            try:
                database = make_url(self.database_connection_url)
            except Exception as exc:
                raise ValueError("DATABASE_URL or SUPABASE_DB_URL must be a valid SQLAlchemy URL") from exc
            if database.get_backend_name() != "postgresql":
                raise ValueError("Supabase PostgreSQL is required in production; configure SUPABASE_DB_URL")
            host = (database.host or "").lower()
            if not (host.endswith(".supabase.co") or host.endswith(".pooler.supabase.com")):
                raise ValueError("Production database host must belong to Supabase (db.<project>.supabase.co or Supabase pooler)")
            origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
            if not origins or "*" in origins or any(not origin.startswith("https://") for origin in origins):
                raise ValueError("CORS_ORIGINS must contain explicit HTTPS origins in production")
            hosts = [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]
            if not hosts or "*" in hosts:
                raise ValueError("TRUSTED_HOSTS must contain explicit hostnames in production")
            if not self.force_https:
                raise ValueError("FORCE_HTTPS must be enabled in production")
            redirect_origins = [item.strip() for item in self.portal_redirect_origins.split(",") if item.strip()]
            if not redirect_origins or any(not item.startswith("https://") for item in redirect_origins):
                raise ValueError("PORTAL_REDIRECT_ORIGINS must contain the exact HTTPS origins of the independently deployed portals")
        if bool(self.bootstrap_admin_email) != bool(self.bootstrap_admin_password):
            raise ValueError("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be configured together")
        if self.bootstrap_admin_password and len(self.bootstrap_admin_password) < 14:
            raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 14 characters")
        return self

settings = Settings()
