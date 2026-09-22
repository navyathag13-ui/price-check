variable "resource_group_name" {
  description = "Resource group all Price Check resources live in (same group used for the manually-created Azure OpenAI / Content Safety resources, so everything is torn down together)."
  type        = string
  default     = "rg-pricecheck"
}

variable "location" {
  description = "Azure region. Must be one this subscription is allowed to deploy to -- verified earlier this project: northcentralus, westus, francecentral, norwayeast, denmarkeast."
  type        = string
  default     = "northcentralus"
}

variable "sql_admin_login" {
  description = "Azure SQL server admin username."
  type        = string
  default     = "pricecheckadmin"
}

variable "sql_admin_password" {
  description = "Azure SQL server admin password. Never hardcoded or defaulted -- pass via TF_VAR_sql_admin_password or a .tfvars file that is gitignored."
  type        = string
  sensitive   = true
}

variable "my_ip" {
  description = "Client IP allowed through the SQL firewall (yours, or Cloud Shell's). Get it with `curl -s ifconfig.me`."
  type        = string
}

variable "budget_amount_usd" {
  description = "Monthly budget alert threshold in USD."
  type        = number
  default     = 10
}

variable "alert_email" {
  description = "Email address for budget and monitor alerts."
  type        = string
}
