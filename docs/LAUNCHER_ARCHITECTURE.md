# Arquitetura auditada — 25/10/2026

## Encontrado

Não há repositório Git nesta pasta. `native/src/mk5_window.cpp` contém o renderer do jogo: Win32 em thread própria, DXGI flip com dois buffers BGRA8, D3D12 hardware feature-level 11, heap RTV e SRV, textura 400x254, fence com timeout de 5 s, upload separado do produtor de jogo/PCM. Shaders HLSL compilados com D3DCompile fazem nearest/bilinear e scanlines. O jogo preserva 4:3 e possui Alt+Enter exclusivo. Entrada do jogo é teclado; XInput não estava integrado no launcher.

`tools/manual-temp-4-20261025/launcher.cpp` é um bootstrap C++ com janela Win32 convencional de configurações. Não existe sistema de UI/ImGui nem ambiente gráfico de launcher a reutilizar. Ele chama `session.ps1`, que valida hashes/ROMs, bloqueia o perfil, inicia o motor, coleta estado a cada 250 ms e salva CMOS original de 16 KB. `LogStore.cs` limita os logs. O motor e suas licenças estão em `build/native/manual-temporary-4-20261025/product`. A descrição anterior de “Remasterizada” significa apenas efeitos de apresentação e será corrigida na nova interface.

## Evolução escolhida

Ampliar o bootstrap nativo com módulos em `native/launcher`, seguindo os padrões DX12 já presentes, sem tocar no produtor nem no renderer do jogo. Alternativas: integrar a UI à thread gráfica do jogo acoplaria os ciclos de vida; trocar por web/Electron contrariaria o pedido e adicionaria dependências. O novo renderer de coleção precisa múltiplas texturas/alpha/quads, recursos ausentes no renderer 4:3 do jogo, portanto não substitui `Mk5Window`.

`launcher_backend.hpp/.cpp`: configuração, disponibilidade, processo de sessão e encerramento. `launcher_renderer.hpp/.cpp`: texturas WIC em cache, atlas de fonte GDI carregado uma vez, root constants, quads/triângulos, efeitos HLSL, resize/fences/readback. `launcher_main.cpp`: Win32, layout, controles, foco, XInput e composição. `tools/manual-temp-5-20261025`: pacote, scripts e provas compactas. EXE na raiz: `MK1-TEMPORARIA-5.exe`.

Configuração única em `build/native/manual-temporary-5-20261025/profile/launcher.ini`: Launcher (FPS, VSync, movimento reduzido, volume de UI, tela cheia) e MK1 (scanlines, filtro). Caminhos relativos à localização do EXE. Novo pacote copia o motor binariamente; a sessão deriva da 4 e altera apenas identificação/perfil e terminologia de apresentação. Processo de jogo é monitorado sem bloquear a UI; fechamento pede WM_CLOSE ao jogo e aguarda a finalização do logger/CMOS.
