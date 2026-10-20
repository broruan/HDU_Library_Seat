param(
    [ValidateSet('Debug', 'Release')]
    [string]$Variant = 'Debug'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
    throw 'Install JDK 17 and set JAVA_HOME before building. See docs/android.md.'
}
if (-not $env:ANDROID_HOME -and -not $env:ANDROID_SDK_ROOT -and -not (Test-Path android/local.properties)) {
    throw 'Install Android SDK 35 and set ANDROID_HOME, or create android/local.properties.'
}
if ($Variant -eq 'Release') {
    foreach ($setting in @('HDU_ANDROID_KEYSTORE_PATH', 'HDU_ANDROID_KEYSTORE_PASSWORD', 'HDU_ANDROID_KEY_ALIAS', 'HDU_ANDROID_KEY_PASSWORD')) {
        if (-not [Environment]::GetEnvironmentVariable($setting)) {
            throw "Release signing requires $setting. See docs/android.md."
        }
    }
}

Push-Location android
try {
    & .\gradlew.bat --no-daemon "assemble$Variant"
    if ($LASTEXITCODE -ne 0) { throw 'Android APK build failed' }
} finally {
    Pop-Location
}

$variantPath = $Variant.ToLowerInvariant()
$suffix = if ($Variant -eq 'Debug') { '-debug' } else { '' }
$destination = Join-Path $PSScriptRoot "dist/android/HDU-Library-Seat-Android$suffix.apk"
New-Item -ItemType Directory -Force (Split-Path $destination) | Out-Null
Copy-Item -LiteralPath "android/app/build/outputs/apk/$variantPath/app-$variantPath.apk" -Destination $destination
Get-FileHash -Algorithm SHA256 -LiteralPath $destination
Write-Output "APK: $destination"
