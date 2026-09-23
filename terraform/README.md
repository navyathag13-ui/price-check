# Terraform

**Quickest way to deploy:** in Azure Cloud Shell, `git clone` this repo, `cd price-check/terraform`, then `ALERT_EMAIL=you@example.com ./cloudshell_deploy.sh`. It checks the resource group, generates the SQL password (saved to a git-ignored file, never printed), shows the plan, and asks before applying. I ran it this way on 2026-09-23 (details below).

`terraform validate` passes locally (checked this session, Terraform 1.9.8, azurerm provider 4.81.0).
**Applied on 2026-09-23** from Azure Cloud Shell using `cloudshell_deploy.sh` (this tenant's Conditional Access blocks Azure CLI and Terraform sign-in from a laptop, so Cloud Shell is the only place `apply` works). The final `terraform apply` reported `Apply complete! Resources: 4 added`, after an earlier run created the other 11. `terraform output` returned:

- storage account `pricecheckadls90608e` (containers `bronze` and `delta`)
- SQL server `pricecheck-sql-90608ea1.database.windows.net` (database `pricecheck`)
- Data Factory `pricecheck-adf`
- Event Hubs namespace `pricecheck-eh-90608ea1`

Things that went wrong and how they were fixed: Azure SQL provisioning is disabled for this subscription in `northcentralus` (`ProvisioningDisabled`), so the SQL server now uses its own `sql_location` variable (default `westus`). The failed attempt left a stub server in `northcentralus` that blocked a same-named server in another region (`InvalidResourceLocation`); `az sql server delete` removed it and the retry succeeded.

The four gold summary tables have since been loaded into the SQL database (see `sql/azure_sql/README.md`). Nothing else has been put in the cloud: no data uploaded to the storage account, no pipelines built. Event Hubs is idle but still billing (Basic tier, about $0.03 per hour). Run `terraform destroy` (or destroy just the Event Hubs namespace) when you don't need it. The commands to run it yourself:

```bash
cd terraform
terraform init
terraform plan -var="sql_admin_password=$(openssl rand -base64 24)" \
                -var="my_ip=$(curl -s ifconfig.me)" \
                -var="alert_email=<your email>"
# review the plan, then:
terraform apply -var="sql_admin_password=..." -var="my_ip=..." -var="alert_email=..."
```

Also provisions an Event Hubs namespace + hub (Basic SKU, ~$0.03/hour if left running -- **not free-tier**, stop/destroy it when not actively testing streaming) for the Phase 9 stretch goal's Kafka-compatible endpoint. `data.azurerm_resource_group.main` imports the resource group (`rg-pricecheck`) and the Azure OpenAI / Content
Safety resources already created manually this session (see the RAG project's session and this project's
`sql/azure_sql/README.md`) -- Terraform does not try to recreate them, only adds what doesn't exist yet: ADLS
Gen2, Azure SQL, Log Analytics + App Insights, Data Factory, and a budget alert.

## Teardown
```bash
terraform destroy -var="sql_admin_password=..." -var="my_ip=..." -var="alert_email=..."
```
This does not delete the resource group itself or the manually-created Azure OpenAI/Content Safety resources
(they're referenced via `data`, not `resource`) -- `az group delete -n rg-pricecheck --yes` removes everything.
