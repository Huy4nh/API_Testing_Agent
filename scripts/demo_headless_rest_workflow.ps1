<#
.SYNOPSIS
  Demo script for API Testing Agent Headless REST Workflow API.

.DESCRIPTION
  This script calls the FastAPI REST adapter for HeadlessWorkflowService.

  It verifies:
  - GET  /health
  - POST /workflows/start
  - POST /workflows/{thread_id}/continue
  - GET  /workflows/{thread_id}/status
  - GET  /workflows/{thread_id}/snapshot
  - GET  /workflows/{thread_id}/artifacts

  Optional:
  - POST /workflows/{thread_id}/cancel

.REQUIREMENTS
  Start the REST server before running this script:

    poetry run uvicorn api_testing_agent.interfaces.rest.headless_workflow_api:app --reload

.USAGE
  From project root:

    powershell -ExecutionPolicy Bypass -File scripts/demo_headless_rest_workflow.ps1

  Or cancel at end:

    powershell -ExecutionPolicy Bypass -File scripts/demo_headless_rest_workflow.ps1 -CancelAtEnd
#>

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",

    [string]$InitialText = "test img",

    [string]$TargetSelectionMessage = "product",

    [string]$ScopeSelectionMessage = "chi test operation POST /img, khong test endpoint khac",

    [switch]$CancelAtEnd
)

$ErrorActionPreference = "Stop"

# Keep console output as UTF-8 when possible.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    chcp 65001 | Out-Null
}
catch {
    # Safe to ignore.
}

function Write-Section {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title
    )

    Write-Host ""
    Write-Host ("=" * 100) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ("=" * 100) -ForegroundColor Cyan
}

function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title
    )

    Write-Host ""
    Write-Host ("-" * 100) -ForegroundColor DarkCyan
    Write-Host $Title -ForegroundColor DarkCyan
    Write-Host ("-" * 100) -ForegroundColor DarkCyan
}

function Convert-ToPrettyJson {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,

        [int]$Depth = 30
    )

    return $Value | ConvertTo-Json -Depth $Depth
}

function Invoke-JsonGet {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri
    )

    Invoke-RestMethod `
        -Method Get `
        -Uri $Uri
}

function Invoke-JsonPost {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [hashtable]$Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 30
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

    Invoke-RestMethod `
        -Method Post `
        -Uri $Uri `
        -ContentType "application/json; charset=utf-8" `
        -Body $bytes
}

function Save-DemoResponse {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [object]$Response
    )

    $outputDir = Join-Path "debug" "headless_rest_demo"
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

    $safeName = $Name -replace "[^a-zA-Z0-9_\-]", "_"
    $path = Join-Path $outputDir ("{0}.json" -f $safeName)

    $Response |
        ConvertTo-Json -Depth 50 |
        Out-File -FilePath $path -Encoding utf8

    Write-Host ""
    Write-Host ("[debug] Saved response: {0}" -f $path) -ForegroundColor DarkGray
}

function Assert-OkResponse {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Response,

        [Parameter(Mandatory = $true)]
        [string]$StepName
    )

    if ($null -eq $Response) {
        throw "Step '$StepName' returned null response."
    }

    if ($Response.PSObject.Properties.Name -contains "ok") {
        if ($Response.ok -ne $true) {
            $json = $Response | ConvertTo-Json -Depth 30
            throw "Step '$StepName' returned ok=false. Response: $json"
        }
    }
}

function Get-WorkflowPhase {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Response
    )

    if ($null -ne $Response.workflow) {
        return [string]$Response.workflow.phase
    }

    if ($null -ne $Response.snapshot) {
        return [string]$Response.snapshot.current_phase
    }

    return ""
}

function Get-WorkflowThreadId {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Response
    )

    if ($null -ne $Response.workflow) {
        return [string]$Response.workflow.thread_id
    }

    if ($null -ne $Response.snapshot) {
        return [string]$Response.snapshot.thread_id
    }

    return ""
}

function Show-WorkflowSummary {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Response
    )

    if ($null -eq $Response.workflow) {
        Write-Host "No workflow object in response." -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "Workflow Summary" -ForegroundColor Green
    Write-Host ("-" * 100)

    Write-Host ("ok                 : {0}" -f $Response.ok)
    Write-Host ("operation          : {0}" -f $Response.operation)
    Write-Host ("workflow_id        : {0}" -f $Response.workflow.workflow_id)
    Write-Host ("thread_id          : {0}" -f $Response.workflow.thread_id)
    Write-Host ("phase              : {0}" -f $Response.workflow.phase)
    Write-Host ("selected_target    : {0}" -f $Response.workflow.selected_target)
    Write-Host ("needs_user_input   : {0}" -f $Response.workflow.needs_user_input)
    Write-Host ("finalized          : {0}" -f $Response.workflow.finalized)
    Write-Host ("cancelled          : {0}" -f $Response.workflow.cancelled)

    if ($Response.workflow.canonical_command) {
        Write-Host ("canonical_command  : {0}" -f $Response.workflow.canonical_command)
    }

    if ($Response.workflow.available_actions) {
        Write-Host ("available_actions  : {0}" -f (($Response.workflow.available_actions) -join ", "))
    }

    if ($Response.workflow.candidate_targets) {
        Write-Host ("candidate_targets  : {0}" -f (($Response.workflow.candidate_targets) -join ", "))
    }

    if ($Response.workflow.artifacts) {
        Write-Host ("artifact_count     : {0}" -f $Response.workflow.artifacts.Count)
    }
    else {
        Write-Host "artifact_count     : 0"
    }

    if ($Response.workflow.assistant_message) {
        Write-Host ""
        Write-Host "Assistant Message" -ForegroundColor Green
        Write-Host ("-" * 100)
        Write-Host $Response.workflow.assistant_message
    }
}

Write-Section "API Testing Agent - Headless REST Workflow Demo"

Write-Host "BaseUrl                : $BaseUrl"
Write-Host "InitialText            : $InitialText"
Write-Host "TargetSelectionMessage : $TargetSelectionMessage"
Write-Host "ScopeSelectionMessage  : $ScopeSelectionMessage"
Write-Host "CancelAtEnd            : $CancelAtEnd"

Write-Step "1. Health check"

$health = Invoke-JsonGet -Uri "$BaseUrl/health"
Write-Host (Convert-ToPrettyJson -Value $health)

if ($health.ok -ne $true) {
    throw "Health check failed."
}

Write-Step "2. Start workflow"

$startPayload = @{
    text = $InitialText
    actor_context = @{
        actor_id = "demo_script"
        session_id = "demo_headless_rest_workflow"
        user_id = "local_user"
        org_id = "local_org"
    }
}

$startResponse = Invoke-JsonPost `
    -Uri "$BaseUrl/workflows/start" `
    -Payload $startPayload

Assert-OkResponse -Response $startResponse -StepName "start_workflow"
Save-DemoResponse -Name "01_start_workflow" -Response $startResponse
Show-WorkflowSummary -Response $startResponse

$threadId = Get-WorkflowThreadId -Response $startResponse

if ([string]::IsNullOrWhiteSpace($threadId)) {
    throw "Cannot continue demo because thread_id is empty."
}

Write-Host ""
Write-Host ("Thread ID: {0}" -f $threadId) -ForegroundColor Green

Write-Step "3. Continue workflow - select target"

$targetPayload = @{
    message = $TargetSelectionMessage
    actor_context = @{
        actor_id = "demo_script"
        session_id = "demo_headless_rest_workflow"
        user_id = "local_user"
        org_id = "local_org"
    }
}

$targetResponse = Invoke-JsonPost `
    -Uri "$BaseUrl/workflows/$threadId/continue" `
    -Payload $targetPayload

Assert-OkResponse -Response $targetResponse -StepName "select_target"
Save-DemoResponse -Name "02_select_target" -Response $targetResponse
Show-WorkflowSummary -Response $targetResponse

$currentPhase = Get-WorkflowPhase -Response $targetResponse

Write-Host ""
Write-Host ("Current phase after target selection: {0}" -f $currentPhase) -ForegroundColor Green

Write-Step "4. Continue workflow - select scope"

$scopePayload = @{
    message = $ScopeSelectionMessage
    actor_context = @{
        actor_id = "demo_script"
        session_id = "demo_headless_rest_workflow"
        user_id = "local_user"
        org_id = "local_org"
    }
}

$scopeResponse = Invoke-JsonPost `
    -Uri "$BaseUrl/workflows/$threadId/continue" `
    -Payload $scopePayload

Assert-OkResponse -Response $scopeResponse -StepName "select_scope"
Save-DemoResponse -Name "03_select_scope" -Response $scopeResponse
Show-WorkflowSummary -Response $scopeResponse

$currentPhase = Get-WorkflowPhase -Response $scopeResponse

Write-Host ""
Write-Host ("Current phase after scope selection: {0}" -f $currentPhase) -ForegroundColor Green

if ($currentPhase -ne "pending_review") {
    Write-Host ""
    Write-Host "Scope selection did not reach pending_review." -ForegroundColor Yellow
    Write-Host "This can happen if the current core scope-confirmation logic asks for more clarification." -ForegroundColor Yellow
    Write-Host "You can continue manually with Swagger UI or REST /continue using the same thread_id." -ForegroundColor Yellow
    Write-Host ("Thread ID: {0}" -f $threadId) -ForegroundColor Yellow
}

Write-Step "5. Read-only status"

$statusResponse = Invoke-JsonGet -Uri "$BaseUrl/workflows/$threadId/status"

Assert-OkResponse -Response $statusResponse -StepName "get_status"
Save-DemoResponse -Name "04_status" -Response $statusResponse
Show-WorkflowSummary -Response $statusResponse

Write-Step "6. Read-only snapshot"

$snapshotResponse = Invoke-JsonGet -Uri "$BaseUrl/workflows/$threadId/snapshot"

Assert-OkResponse -Response $snapshotResponse -StepName "get_snapshot"
Save-DemoResponse -Name "05_snapshot" -Response $snapshotResponse

Write-Host ""
Write-Host "Snapshot Summary" -ForegroundColor Green
Write-Host ("-" * 100)

if ($null -ne $snapshotResponse.snapshot) {
    Write-Host ("workflow_id       : {0}" -f $snapshotResponse.snapshot.workflow_id)
    Write-Host ("thread_id         : {0}" -f $snapshotResponse.snapshot.thread_id)
    Write-Host ("current_phase     : {0}" -f $snapshotResponse.snapshot.current_phase)
    Write-Host ("current_target    : {0}" -f $snapshotResponse.snapshot.current_target)
    Write-Host ("pending_question  : {0}" -f $snapshotResponse.snapshot.pending_question)
    Write-Host ("active_review_id  : {0}" -f $snapshotResponse.snapshot.active_review_id)
    Write-Host ("active_report_id  : {0}" -f $snapshotResponse.snapshot.active_report_session_id)
}
else {
    Write-Host "No snapshot object returned." -ForegroundColor Yellow
}

Write-Step "7. Read-only artifacts"

$artifactsResponse = Invoke-JsonGet -Uri "$BaseUrl/workflows/$threadId/artifacts"

Assert-OkResponse -Response $artifactsResponse -StepName "list_artifacts"
Save-DemoResponse -Name "06_artifacts" -Response $artifactsResponse

Write-Host ""
Write-Host "Artifacts" -ForegroundColor Green
Write-Host ("-" * 100)

if ($artifactsResponse.artifacts -and $artifactsResponse.artifacts.Count -gt 0) {
    foreach ($artifact in $artifactsResponse.artifacts) {
        Write-Host ("- [{0}] {1}: {2}" -f $artifact.stage, $artifact.artifact_type, $artifact.path)
    }
}
else {
    Write-Host "No artifacts yet. This is expected before the workflow reaches pending_review or later phases."
}

if ($CancelAtEnd) {
    Write-Step "8. Cancel workflow"

    $cancelPayload = @{
        auto_confirm = $true
        cancel_message = "huy"
        confirmation_message = "dong y"
        actor_context = @{
            actor_id = "demo_script"
            session_id = "demo_headless_rest_workflow"
            user_id = "local_user"
            org_id = "local_org"
        }
    }

    $cancelResponse = Invoke-JsonPost `
        -Uri "$BaseUrl/workflows/$threadId/cancel" `
        -Payload $cancelPayload

    Assert-OkResponse -Response $cancelResponse -StepName "cancel_workflow"
    Save-DemoResponse -Name "07_cancel" -Response $cancelResponse
    Show-WorkflowSummary -Response $cancelResponse
}
else {
    Write-Step "8. Cancel skipped"

    Write-Host "CancelAtEnd was not provided."
    Write-Host "The workflow remains available for manual continuation."
}

Write-Section "Demo completed"

Write-Host ("Thread ID: {0}" -f $threadId) -ForegroundColor Green
Write-Host "Saved debug responses under: debug\headless_rest_demo" -ForegroundColor Green
Write-Host ""
Write-Host "Useful next commands:" -ForegroundColor Cyan
Write-Host ("  GET  {0}/workflows/{1}/status" -f $BaseUrl, $threadId)
Write-Host ("  GET  {0}/workflows/{1}/snapshot" -f $BaseUrl, $threadId)
Write-Host ("  GET  {0}/workflows/{1}/artifacts" -f $BaseUrl, $threadId)
Write-Host ("  POST {0}/workflows/{1}/continue" -f $BaseUrl, $threadId)