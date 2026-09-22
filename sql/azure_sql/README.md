# Azure SQL Database serving layer

**Not created automatically.** The university tenant's Conditional Access policy blocks the Azure CLI from this
machine (same constraint hit in the RAG project) -- these commands must be run by the user in **Azure Cloud Shell**.

## What gets created and the cost
Azure SQL Database **free offer** (verified earlier this session): 100,000 vCore-seconds + 32 GB storage per database
per month, free for the lifetime of the subscription, up to 10 free databases per subscription. **Expected cost: $0**,
as long as the "Auto-pause the database until next month" option is kept (the default) rather than "continue for
additional charges". This project's data (4 tables, largest ~128K rows) is nowhere near the 32 GB limit.

```bash
# Run in Azure Cloud Shell (Bash), in the SAME resource group as the RAG project's resources (rg-pricecheck)
# so everything for this account lives in one place and is easy to tear down together.
RG=rg-pricecheck
LOC=northcentralus            # same region verified earlier for this subscription's allowed regions
SERVER=pricecheck-sql-$RANDOM
DB=pricecheck

az sql server create --name $SERVER --resource-group $RG --location $LOC \
    --admin-user pricecheckadmin --admin-password "$(openssl rand -base64 24)"   # SAVE the printed password, shown once

az sql db create --resource-group $RG --server $SERVER --name $DB \
    --edition GeneralPurpose --compute-model Serverless --family Gen5 --capacity 1 \
    --use-free-limit --free-limit-exhaustion-behavior AutoPause

# Allow your current IP (Cloud Shell's IP, or your laptop's) to connect:
MYIP=$(curl -s ifconfig.me)
az sql server firewall-rule create --resource-group $RG --server $SERVER \
    --name allow-my-ip --start-ip-address $MYIP --end-ip-address $MYIP
# Also allow Azure services (needed if ADF/Functions connect to it in Phase 8):
az sql server firewall-rule create --resource-group $RG --server $SERVER \
    --name allow-azure-services --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0

echo "Server: $SERVER.database.windows.net   Database: $DB"
```

## Load the gold marts (run locally, from this Mac)
Put the connection details in `.env` (gitignored, never in the repo) and run the loader:
```bash
export AZURE_SQL_SERVER="<server>.database.windows.net"
export AZURE_SQL_DATABASE="pricecheck"
export AZURE_SQL_USER="pricecheckadmin"
export AZURE_SQL_PASSWORD="<the password saved above>"
python -m pricecheck.serving.load_azure_sql
```
This applies `001_schema.sql` + `002_views.sql` and loads `dim_hospital` (21 rows), `dim_procedure_code` (79,213),
`mart_price_comparison` (128,372), `mart_hospital_quality` (21) from the local dbt-built DuckDB file. **Not run in
this session** -- no Azure SQL Database exists yet to load into; see README.md "What's verified vs. not" for the
honest split, same pattern as the RAG project.

## Teardown
```bash
az sql server delete --name $SERVER --resource-group $RG --yes
```
