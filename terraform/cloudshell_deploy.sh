#!/usr/bin/env bash
# Deploy the Price Check Azure resources from Azure Cloud Shell.
#
# Why Cloud Shell: my university tenant's Conditional Access policy blocks Azure CLI and
# Terraform sign-in from a laptop, but Cloud Shell is already signed in and has Terraform.
#
# Usage (inside Cloud Shell, Bash):
#   git clone https://github.com/navyathag13-ui/price-check.git && cd price-check/terraform
#   ALERT_EMAIL=you@example.com ./cloudshell_deploy.sh
#
# It shows the plan and asks before applying. The SQL admin password is generated here,
# saved to ./.sql_admin_password (mode 600, git-ignored) and never printed.
set -euo pipefail

: "${ALERT_EMAIL:?Set ALERT_EMAIL to the address that should receive budget alerts}"
RG="${RG:-rg-pricecheck}"

echo "Checking the resource group $RG exists (Terraform imports it, it does not create it)..."
az group show -n "$RG" --query name -o tsv

if [ ! -f .sql_admin_password ]; then
  ( umask 077; openssl rand -base64 24 | tr -d '\n' > .sql_admin_password )
fi
export TF_VAR_sql_admin_password="$(cat .sql_admin_password)"
export TF_VAR_my_ip="$(curl -s ifconfig.me)"
export TF_VAR_alert_email="$ALERT_EMAIL"

terraform init -input=false
terraform validate
terraform plan -input=false -out=tfplan

echo
echo "Event Hubs (Basic) costs about \$0.03/hour while it exists. Everything else is on free tiers."
read -r -p "Apply this plan? (type 'yes') " answer
[ "$answer" = "yes" ] || { echo "Not applied."; exit 0; }

terraform apply -input=false tfplan

echo
echo "Deployed. Non-secret outputs:"
terraform output adls_account_name
terraform output sql_server_fqdn
terraform output data_factory_name
terraform output eventhub_namespace_name
echo
echo "To remove everything Terraform created:  terraform destroy"
