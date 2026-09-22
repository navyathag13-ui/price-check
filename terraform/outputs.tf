output "adls_account_name" {
  value = azurerm_storage_account.adls.name
}
output "sql_server_fqdn" {
  value = azurerm_mssql_server.sql.fully_qualified_domain_name
}
output "app_insights_connection_string" {
  value     = azurerm_application_insights.appi.connection_string
  sensitive = true
}
output "data_factory_name" {
  value = azurerm_data_factory.adf.name
}
