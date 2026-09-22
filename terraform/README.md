# Terraform

`terraform validate` passes locally (checked this session, Terraform 1.9.8, azurerm provider 4.81.0).
`terraform plan`/`apply` were **not run** -- same Conditional Access constraint documented throughout this
project (and the RAG project before it): this tenant blocks non-interactive Azure CLI/SDK auth from outside the
portal/Cloud Shell, and `terraform apply` needs that auth. Run it yourself in Cloud Shell:

```bash
cd terraform
terraform init
terraform plan -var="sql_admin_password=$(openssl rand -base64 24)" \
                -var="my_ip=$(curl -s ifconfig.me)" \
                -var="alert_email=<your email>"
# review the plan, then:
terraform apply -var="sql_admin_password=..." -var="my_ip=..." -var="alert_email=..."
```

`data.azurerm_resource_group.main` imports the resource group (`rg-pricecheck`) and the Azure OpenAI / Content
Safety resources already created manually this session (see the RAG project's session and this project's
`sql/azure_sql/README.md`) -- Terraform does not try to recreate them, only adds what doesn't exist yet: ADLS
Gen2, Azure SQL, Log Analytics + App Insights, Data Factory, and a budget alert.

## Teardown
```bash
terraform destroy -var="sql_admin_password=..." -var="my_ip=..." -var="alert_email=..."
```
This does not delete the resource group itself or the manually-created Azure OpenAI/Content Safety resources
(they're referenced via `data`, not `resource`) -- `az group delete -n rg-pricecheck --yes` removes everything.
