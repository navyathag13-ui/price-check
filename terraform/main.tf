# Price Check infrastructure. Everything the running system needs is defined here -- what was created manually
# this session (resource group, Azure OpenAI, Content Safety in the shared RAG project's session) is imported
# via `data` blocks rather than re-declared, so `terraform apply` does not try to recreate them. See DECISIONS.md
# ADR-022 for why apply was never actually run in this session (Conditional Access blocks the CLI here).

data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

# ── Storage: ADLS Gen2 for bronze (raw, immutable, hash-addressed files) ─────────────────────────────────────────
resource "azurerm_storage_account" "adls" {
  name                     = "pricecheckadls${substr(md5(data.azurerm_resource_group.main.id), 0, 6)}"
  resource_group_name      = data.azurerm_resource_group.main.name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # cheapest redundancy; this is a portfolio project, not production
  account_kind             = "StorageV2"
  is_hns_enabled           = true # Hierarchical namespace = ADLS Gen2, not plain blob storage
}

resource "azurerm_storage_data_lake_gen2_filesystem" "bronze" {
  name               = "bronze"
  storage_account_id = azurerm_storage_account.adls.id
}

resource "azurerm_storage_data_lake_gen2_filesystem" "delta" {
  name               = "delta" # silver/gold Delta tables
  storage_account_id = azurerm_storage_account.adls.id
}

# ── Azure SQL: gold marts serving layer (free offer -- see sql/azure_sql/README.md) ────────────────────────────
resource "azurerm_mssql_server" "sql" {
  name                         = "pricecheck-sql-${substr(md5(data.azurerm_resource_group.main.id), 0, 8)}"
  resource_group_name          = data.azurerm_resource_group.main.name
  location                     = var.location
  version                      = "12.0"
  administrator_login          = var.sql_admin_login
  administrator_login_password = var.sql_admin_password
  minimum_tls_version          = "1.2"
}

resource "azurerm_mssql_database" "gold" {
  name                        = "pricecheck"
  server_id                   = azurerm_mssql_server.sql.id
  sku_name                    = "GP_S_Gen5_1" # General Purpose Serverless, Gen5, 1 vCore -- required shape for the free offer
  min_capacity                = 0.5
  auto_pause_delay_in_minutes = 60
  # Free offer (100,000 vCore-seconds + 32GB/month) is a subscription-level benefit applied automatically to the
  # first eligible database, not a Terraform-settable property as of provider v4 -- verify in the portal after apply.
}

resource "azurerm_mssql_firewall_rule" "my_ip" {
  name             = "allow-my-ip"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = var.my_ip
  end_ip_address   = var.my_ip
}

resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ── Observability: Log Analytics + Application Insights ─────────────────────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "law" {
  name                = "pricecheck-logs"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30 # first 5GB/month ingestion is free regardless of retention setting
}

resource "azurerm_application_insights" "appi" {
  name                = "pricecheck-appi"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = var.location
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "other"
}

# ── Orchestration: Azure Data Factory (Databricks Free Edition's outbound-network + no-custom-storage
# restrictions, verified earlier in this project, rule it out for reading our own ADLS account) ───────────────
resource "azurerm_data_factory" "adf" {
  name                = "pricecheck-adf"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = var.location
  # First 1,000 pipeline-orchestration activity runs/month are free (verified this project); this portfolio
  # project's scheduled runs are nowhere near that.
}

# ── Cost control: budget alert ─────────────────────────────────────────────────────────────────────────────────
resource "azurerm_consumption_budget_resource_group" "budget" {
  name              = "pricecheck-monthly-budget"
  resource_group_id = data.azurerm_resource_group.main.id
  amount            = var.budget_amount_usd
  time_grain        = "Monthly"

  time_period {
    start_date = "2026-09-01T00:00:00Z"
  }

  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    contact_emails = [var.alert_email]
  }
  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    contact_emails = [var.alert_email]
  }
  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    contact_emails = [var.alert_email]
  }
}
