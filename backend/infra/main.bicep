// Financial RAG platform.
//
// Every data-plane permission is granted to a user-assigned managed identity
// via RBAC role assignments - no keys are emitted as outputs and none reach
// application config.

targetScope = 'resourceGroup'

@description('Short environment name, e.g. dev / prod.')
param environmentName string = 'dev'

@description('Base name for resources; must be globally unique-ish.')
param baseName string = 'finrag'

param location string = resourceGroup().location

@description('Enable the semantic ranker tier on AI Search. Separately billed.')
param enableSemanticRanker bool = true

@description('Which provider serves generation, embeddings and the eval judge.')
@allowed(['gemini', 'azureOpenAI'])
param llmProvider string = 'gemini'

@secure()
@description('Gemini API key. Stored in Key Vault; the app fetches it with its managed identity so it never reaches container config.')
param geminiApiKey string = ''

@secure()
@description('Administrator password for PostgreSQL flexible server.')
param postgresAdminPassword string

param postgresAdminUser string = 'ragadmin'

var suffix = uniqueString(resourceGroup().id)
var name = '${baseName}-${environmentName}'
var tags = { workload: 'financial-rag', environment: environmentName }

// --------------------------------------------------------------------------
// Identity
// --------------------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-id'
  location: location
  tags: tags
}

// --------------------------------------------------------------------------
// Storage: raw documents, parsed cache, ingest queue
// --------------------------------------------------------------------------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: toLower(replace('${baseName}${environmentName}${take(suffix, 6)}', '-', ''))
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource rawContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'raw'
}

// Parsing is the slow, billed step; its output is cached so a re-index does
// not re-parse.
resource parsedContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'parsed'
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource ingestQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'ingest'
}

// --------------------------------------------------------------------------
// AI services
// --------------------------------------------------------------------------

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: '${name}-search'
  location: location
  tags: tags
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    semanticSearch: enableSemanticRanker ? 'standard' : 'disabled'
    // Keys exist but are unused; the app authenticates with its identity.
    authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } }
  }
}

resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (llmProvider == 'azureOpenAI') {
  name: '${name}-openai'
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: '${name}-openai'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource docIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${name}-docintel'
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: '${name}-docintel'
    disableLocalAuth: true
  }
}

// Deployments. The judge is separate from the generator so eval never competes
// with serving traffic for quota, and so a model never grades its own output.
resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (llmProvider == 'azureOpenAI') {
  parent: openai
  name: 'gpt-4o-mini'
  sku: { name: 'Standard', capacity: 100 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o-mini', version: '2024-07-18' }
  }
}

resource judgeDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (llmProvider == 'azureOpenAI') {
  parent: openai
  name: 'gpt-4.1'
  sku: { name: 'Standard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1', version: '2025-04-14' }
  }
  dependsOn: [ chatDeployment ]
}

resource embedDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (llmProvider == 'azureOpenAI') {
  parent: openai
  name: 'text-embedding-3-large'
  sku: { name: 'Standard', capacity: 150 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-large', version: '1' }
  }
  dependsOn: [ judgeDeployment ]
}

// --------------------------------------------------------------------------
// Data
// --------------------------------------------------------------------------

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${name}-pg'
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource ragDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'ragmeta'
}

// --------------------------------------------------------------------------
// Observability and secrets
// --------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-ai'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${take(name, 18)}-kv'
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource geminiSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' =
  if (llmProvider == 'gemini' && !empty(geminiApiKey)) {
  parent: keyVault
  name: 'gemini-api-key'
  properties: {
    value: geminiApiKey
    contentType: 'Gemini API key'
  }
}

// --------------------------------------------------------------------------
// Container Apps
// --------------------------------------------------------------------------

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// --------------------------------------------------------------------------
// RBAC - data-plane roles, not admin keys
// --------------------------------------------------------------------------

var roles = {
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}

resource searchDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, roles.searchIndexDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource searchServiceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, roles.searchServiceContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource openaiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (llmProvider == 'azureOpenAI') {
  scope: openai
  name: guid(openai.id, identity.id, roles.cognitiveServicesOpenAIUser)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource docIntelRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: docIntelligence
  name: guid(docIntelligence.id, identity.id, roles.cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.storageBlobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource queueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.storageQueueDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', roles.storageQueueDataContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, identity.id, roles.keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --------------------------------------------------------------------------
// Outputs - endpoints only. No keys, by design.
// --------------------------------------------------------------------------

output managedIdentityClientId string = identity.properties.clientId
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output llmProvider string = llmProvider
output openaiEndpoint string = llmProvider == 'azureOpenAI' ? openai.properties.endpoint : ''
output docIntelligenceEndpoint string = docIntelligence.properties.endpoint
output storageAccountUrl string = storage.properties.primaryEndpoints.blob
output containerEnvironmentId string = containerEnv.id
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output keyVaultUri string = keyVault.properties.vaultUri
