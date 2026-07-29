#!/usr/bin/env pwsh

[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Output "Usage: setup-tasks.ps1 [-Json] [-Help]"
    exit 0
}

# Source common functions
. "$PSScriptRoot/common.ps1"

# Get feature paths
$paths = Get-FeaturePathsEnv

if (-not (Test-Path $paths.IMPL_PLAN -PathType Leaf)) {
    [Console]::Error.WriteLine("ERROR: plan.yaml not found in $($paths.FEATURE_DIR)")
    $planCommand = '/speckit-plan'
    [Console]::Error.WriteLine("Run $planCommand first to create the implementation plan.")
    exit 1
}

if (-not (Test-Path $paths.FEATURE_SPEC -PathType Leaf)) {
    [Console]::Error.WriteLine("ERROR: spec.yaml not found in $($paths.FEATURE_DIR)")
    $specifyCommand = '/speckit-specify'
    [Console]::Error.WriteLine("Run $specifyCommand first to create the feature structure.")
    exit 1
}

# Gate (hard abort): both spec.yaml and plan.yaml must pass their schemas before task generation starts
if (-not (Invoke-ValidationGate -SchemaName 'spec' -YamlPath $paths.FEATURE_SPEC -RepoRoot $paths.REPO_ROOT)) {
    [Console]::Error.WriteLine("ERROR: $($paths.FEATURE_SPEC) failed schema validation. Fix the violations above before proceeding to task generation.")
    exit 1
}
if (-not (Invoke-ValidationGate -SchemaName 'plan' -YamlPath $paths.IMPL_PLAN -RepoRoot $paths.REPO_ROOT)) {
    [Console]::Error.WriteLine("ERROR: $($paths.IMPL_PLAN) failed schema validation. Fix the violations above before proceeding to task generation.")
    exit 1
}

# Build available docs list
$docs = @()
if (Test-Path $paths.RESEARCH) { $docs += 'research.md' }
if (Test-Path $paths.DATA_MODEL) { $docs += 'data-model.md' }
$dataModelYaml = Join-Path $paths.FEATURE_DIR 'data-model.yaml'
if (Test-Path $dataModelYaml) { $docs += 'data-model.yaml' }
$contractsYaml = Join-Path $paths.FEATURE_DIR 'contracts.yaml'
if (Test-Path $contractsYaml) { $docs += 'contracts.yaml' }
if ((Test-Path $paths.CONTRACTS_DIR) -and (Get-ChildItem -Path $paths.CONTRACTS_DIR -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    $docs += 'contracts/'
}
if (Test-Path $paths.QUICKSTART) { $docs += 'quickstart.md' }

# Resolve tasks template through override stack
$tasksTemplate = Resolve-Template -TemplateName 'tasks-template' -RepoRoot $paths.REPO_ROOT
if (-not $tasksTemplate -or -not (Test-Path -LiteralPath $tasksTemplate -PathType Leaf)) {
    $expectedCoreTemplate = Join-Path $paths.REPO_ROOT '.specify/templates/tasks-template.md'
    [Console]::Error.WriteLine("ERROR: Tasks template not found for repository root: $($paths.REPO_ROOT)`nTemplate resolution order: overrides -> presets -> extensions -> core.`nExpected shared/core template location: $expectedCoreTemplate`nTo continue, verify whether 'tasks-template.md' is available in '.specify/templates/overrides/', preset templates, extension templates, or restore the shared/core templates (for example by re-running 'specify init') so that '.specify/templates/tasks-template.md' exists.")
    exit 1
}
$tasksTemplate = (Resolve-Path -LiteralPath $tasksTemplate).Path

# Output results
if ($Json) {
    [PSCustomObject]@{
        FEATURE_DIR    = $paths.FEATURE_DIR
        AVAILABLE_DOCS = $docs
        TASKS_TEMPLATE = $tasksTemplate
    } | ConvertTo-Json -Compress
} else {
    Write-Output "FEATURE_DIR: $($paths.FEATURE_DIR)"
    Write-Output "TASKS_TEMPLATE: $(if ($tasksTemplate) { $tasksTemplate } else { 'not found' })"
    Write-Output "AVAILABLE_DOCS:"
    Test-FileExists -Path $paths.RESEARCH -Description 'research.md' | Out-Null
    Test-FileExists -Path $paths.DATA_MODEL -Description 'data-model.md' | Out-Null
    Test-DirHasFiles -Path $paths.CONTRACTS_DIR -Description 'contracts/' | Out-Null
    Test-FileExists -Path $paths.QUICKSTART -Description 'quickstart.md' | Out-Null
}
