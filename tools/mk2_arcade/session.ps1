param(
 [Parameter(Mandatory=$true)][string]$ProjectRoot,
 [ValidateRange(0,500000)][int]$WindowFrames=0,
 [ValidateSet('original')][string]$GameMode='original',
 [ValidateSet('original','presentation')][string]$VisualMode='original',
 [ValidateRange(0,0.75)][double]$Scanlines=0,
 [ValidateSet('nearest','linear')][string]$Filter='nearest',
 [ValidateSet('off')][string]$CrtPreset='off',
 [ValidateSet('vsync','immediate')][string]$SyncMode='immediate',
 [ValidateSet('original','vivid','warm')][string]$ColorMode='original',
 [ValidateRange(80,120)][int]$Brightness=100,
 [ValidateSet('0','1')][string]$Bezel='1',
 [ValidateSet('0')][string]$HighRefresh='0',
 [ValidateSet('low','balanced','safe')][string]$AudioLatency='balanced',
 [switch]$InspectOnly,[switch]$Headless,[switch]$InitializeOnly
)
$ErrorActionPreference='Stop'
function SHA256([string]$Value) {
 $stream=[IO.File]::OpenRead($Value);$hasher=[Security.Cryptography.SHA256]::Create()
 try{return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}
 finally{$stream.Dispose();$hasher.Dispose()}
}
function Guard-Path([string]$Value) {
 $cursor=[IO.Path]::GetFullPath($Value)
 while($cursor) {
  if(Test-Path -LiteralPath $cursor) {
   if(([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw "Linked path: $cursor"}
  }
  $parent=[IO.Directory]::GetParent($cursor)
  if($null -eq $parent){break};$cursor=$parent.FullName
 }
}
function Quote-Native([string]$Value) {
 $text=New-Object Text.StringBuilder;[void]$text.Append('"');$slashes=0
 foreach($character in $Value.ToCharArray()) {
  if($character -eq '\'){$slashes++;continue}
  if($character -eq '"'){[void]$text.Append(('\'*($slashes*2+1)))}else{[void]$text.Append(('\'*$slashes))}
  [void]$text.Append($character);$slashes=0
 }
 [void]$text.Append(('\'*($slashes*2)));[void]$text.Append('"');return $text.ToString()
}
$root=[IO.Path]::GetFullPath($ProjectRoot);Guard-Path $root
$stage=Join-Path $root 'build/native/mk2-arcade-v1';$product=Join-Path $stage 'product'
$manifestPath=Join-Path $product 'manifest.json';Guard-Path $manifestPath
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$core=[IO.Path]::GetFullPath($manifest.core_path);Guard-Path $core
if((SHA256 $core) -ne $manifest.core_sha256){throw 'Core SHA-256 differs from the installed MK2 product'}
if($manifest.roms_required.Count -ne 20){throw 'MK2 L3.1 requires exactly 20 authenticated ROMs'}
$romRoot=[IO.Path]::GetFullPath((Join-Path $product 'roms'))
foreach($rom in $manifest.roms_required) {
 $file=[IO.Path]::GetFullPath((Join-Path $romRoot $rom.path));Guard-Path $file
 if(-not $file.StartsWith($romRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'ROM path escapes the product'}
 if((Get-Item -LiteralPath $file).Length -ne $rom.size -or (SHA256 $file) -ne $rom.sha256){throw "ROM SHA-256 or size differs: $($rom.path)"}
}
$seed=Join-Path $product 'factory-default-cmos.bin';Guard-Path $seed
if((Get-Item -LiteralPath $seed).Length -ne 16384 -or (SHA256 $seed) -ne $manifest.factory_cmos.sha256){throw 'Factory CMOS SHA-256 differs'}
$profile=Join-Path $stage 'profile'
$coreArgs=@('mk2','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins','-noconfirm_quit','-noautosave','-norewind','-nodebug','-nolog','-nooslog',
 '-rompath',$romRoot,'-homepath',(Join-Path $profile 'home'),'-cfg_directory',(Join-Path $profile 'cfg'),
 '-nvram_directory',(Join-Path $profile 'nvram'),'-state_directory',(Join-Path $profile 'state'),'-snapshot_directory',(Join-Path $profile 'snap'),
 '-input_directory',(Join-Path $profile 'input'),'-diff_directory',(Join-Path $profile 'diff'),
 '-ctrlrpath',(Join-Path $product 'controls'),'-ctrlr','mk2-default','-joystick','-joystickprovider','xinput',
 '-artpath',(Join-Path $product 'artwork'),'-view',$(if($Bezel -eq '1'){'Moldura'}else{'Original'}),
 '-speed','1','-throttle','-norefreshspeed','-nosyncrefresh','-frameskip','0','-noautoframeskip',
 '-video',$(if($Headless){'none'}else{'d3d'}),'-sound',$(if($Headless){'none'}else{'auto'}),'-window','-maximize',
 '-samplerate','48000','-audio_latency',$(if($AudioLatency -eq 'safe'){'0.14'}else{'0.08'}),
 '-brightness',(($Brightness/100.0).ToString('F2',[Globalization.CultureInfo]::InvariantCulture)),
 $(if($Filter -eq 'linear'){'-filter'}else{'-nofilter'}),$(if($SyncMode -eq 'vsync'){'-waitvsync'}else{'-nowaitvsync'}),
 '-nolowlatency')
$alpha=$Scanlines
if($alpha -gt 0 -or $ColorMode -ne 'original'){
 $coreArgs+=@('-hlsl_enable','-hlslpath',(Join-Path ([IO.Path]::GetDirectoryName($core)) 'hlsl'),'-scanline_alpha',$alpha.ToString([Globalization.CultureInfo]::InvariantCulture))
 if($ColorMode -eq 'vivid'){$coreArgs+=@('-saturation','1.12','-contrast','1.05')}
 if($ColorMode -eq 'warm'){$coreArgs+=@('-scale','1.04,1.0,0.92')}
}else{$coreArgs+='-nohlsl_enable'}
if($WindowFrames -gt 0){$coreArgs+=@('-seconds_to_run',[string][Math]::Ceiling($WindowFrames/54.70684))}
if($Headless){$coreArgs+='-nothrottle'}
if($InspectOnly){@{core=$core;arguments=@($coreArgs);profile=$profile} | ConvertTo-Json -Depth 5;exit 0}
foreach($name in @('home','cfg','nvram','state','snap','input','diff')){
 $directory=Join-Path $profile $name;Guard-Path $directory;[void][IO.Directory]::CreateDirectory($directory);Guard-Path $directory
}
$nvram=Join-Path $profile 'nvram/mk2/nvram';Guard-Path $nvram
[void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($nvram))
if(-not (Test-Path -LiteralPath $nvram)){[IO.File]::Copy($seed,$nvram,$false)}
if($InitializeOnly){@{initialized=$true;nvram=$nvram} | ConvertTo-Json;exit 0}
$result=[ordered]@{game='mk2';revision='L3.1';core='MAME 0.280';started_utc=[DateTime]::UtcNow.ToString('o');exit_code=1;original_clock=$true}
try {
 $process=New-Object Diagnostics.Process
 $process.StartInfo.FileName=$core;$process.StartInfo.Arguments=($coreArgs | ForEach-Object {Quote-Native ([string]$_)}) -join ' '
 $process.StartInfo.WorkingDirectory=[IO.Path]::GetDirectoryName($core);$process.StartInfo.UseShellExecute=$false
 $process.StartInfo.RedirectStandardOutput=$true;$process.StartInfo.RedirectStandardError=$true
 [void]$process.Start();$result.pid=$process.Id
 $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync();$process.WaitForExit()
 $result.exit_code=$process.ExitCode
 foreach($pending in @($stdout,$stderr)){$text=$pending.GetAwaiter().GetResult();if($text){Write-Output $text.Substring([Math]::Max(0,$text.Length-4096))}}
 $process.Dispose()
}catch{$result.error=$_.Exception.Message;Write-Error $_ -ErrorAction Continue}
finally {
 $result.ended_utc=[DateTime]::UtcNow.ToString('o');$logDirectory=Join-Path $root 'logs/mk2-v1';Guard-Path $logDirectory;[void][IO.Directory]::CreateDirectory($logDirectory)
 $summary=Join-Path $logDirectory 'latest.json';Guard-Path $summary;$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
}
exit $result.exit_code
