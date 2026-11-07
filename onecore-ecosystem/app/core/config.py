from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "OneCore Technologies Ltd"
    app_env: str = "development"
    debug: bool = False
    secret_key: str = Field(default="unsafe-development-key-change-me")
    access_token_expire_minutes: int = 30
    database_url: str = "sqlite:///./onecore.db"
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    bootstrap_admin_email: str = "admin@onecore.local"
    bootstrap_admin_password: str = "ChangeThis-Immediately-123!"

    integration_mpesa_enabled: bool = False
    mpesa_base_url: str = ""
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = ""
    mpesa_passkey: str = ""
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

    integration_sms_enabled: bool = False
    sms_base_url: str = ""
    sms_api_key: str = ""
    sms_sender_id: str = ""

    integration_whatsapp_enabled: bool = False
    whatsapp_base_url: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""

    integration_ai_enabled: bool = False
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""

    integration_object_storage_enabled: bool = False
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = ""
    s3_region: str = ""

settings = Settings()
