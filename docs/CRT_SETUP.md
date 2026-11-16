O guia atual da Temporária 7 está em [DISPLAY_INPUT_SETUP.md](DISPLAY_INPUT_SETUP.md),
com CRT Energia, cores, molduras, VRR e controles. O texto abaixo documenta a
entrega histórica da Temporária 6 e seus parâmetros/testes específicos.

# CRT do MK1 — Temporária 6

O motor incorpora o HLSL em `native/include/mk5_crt_shader.hpp`. A compilação usa D3DCompiler/Shader Model 5 e o pipeline D3D12 já existente: uma textura de entrada, um triângulo e uma passagem, sem textura intermediária, arquivo de shader instalado ou download. `native/include/mk5_crt.hpp` controla padrões, validação e a referência escalar do teste opcional.

## Seleção

1. Abra `MK1-TEMPORARIA-6.exe`, entre em SETTINGS > VIDEO e clique em SCANLINES até o perfil BVM desejado. Use SALVAR e inicie o jogo.
2. Use a resolução nativa do monitor. Escolha BVM 1080p para a máscara M/G de dois pixels ou BVM 4K para R/G/B/black de quatro pixels. A escolha é explícita; ambos funcionam em outras resoluções.
3. Mantenha nearest na textura de entrada. No BVM o controlador já impõe isso; o shader faz a reconstrução gaussiana em luz linear, sem filtragem vertical bilinear adicional nem mipmaps.
4. A escala vertical é `k=floor(min(altura_saida,largura_saida*3/4)/254)`. Para `k>=1`, a imagem terá altura `254*k` e largura `altura*4/3`, centralizada. Essa correção do pixel aspect ratio preserva a proporção do gabinete. Em 1080p, `k=4`; em 4K, `k=8`.
5. A passagem vai diretamente ao backbuffer na resolução de saída. Evite redimensionar esse resultado novamente no driver ou no monitor: a máscara precisa permanecer em pixels físicos. Margens pretas maiores são esperadas com escala inteira.
6. Para ajuste fino, defina as variáveis da tabela antes de abrir o launcher e selecione um BVM no SETTINGS. A sessão controla `MK1_CRT_PRESET` pela seleção salva; definir apenas essa variável no ambiente não substitui a seleção do launcher.

`MK1_CRT_PRESET` aceita `off` (padrão), `bvm-1080`, `bvm-4k` e `bvm-soft`. O launcher associa suas opções 4, 5 e 6 aos três presets CRT. Com `off`, permanecem `MK1_FILTER=nearest|linear` e `MK1_SCANLINES=0..1`. No CRT, a entrada é sempre nearest, os texels são lidos explicitamente e as scanlines simples não se acumulam com o feixe. Valores legados inválidos continuam sendo rejeitados, inclusive quando CRT está ativo.

O buffer original inteiro de **400×254** permanece na textura. A razão física é 4:3. Acima de 1×, a altura é um múltiplo inteiro de 254: 1016 em uma saída 1920×1080 e 2032 em 3840×2160. A largura acompanha 4:3; as margens são pretas. Abaixo de 1×, a imagem inteira cabe na janela e a modulação vertical é reduzida para evitar uma máscara de feixe subpixel. A renderização não altera o estado do jogo, PCM nem o relógio do produtor.

## Reconstrução

A entrada passa para luz linear por `gamma_in`. A reconstrução horizontal combina o texel nearest com um kernel gaussiano normalizado de três taps; a mistura é moderada para preservar detalhes. Três linhas vizinhas contribuem ao feixe gaussiano vertical. Seu sigma cresce com a raiz da luminância linear, permitindo maior largura em detalhes claros. `scanline_weight` mistura o feixe com a linha sem modulação. A halation local é limitada e multiplicada pela energia do sinal central; uma entrada totalmente preta continua exatamente preta. A saída recebe ganho e máscara em luz linear, passa por saturação e por `gamma_out`.

A grille é contínua na vertical e usa `floor(SV_Position.x)`, sem contador de frames ou fase animada. O preset 1080 usa **M/G, dois pixels físicos por período**, com `mask_scale=1`. O 4K usa **R/G/B/black, quatro pixels físicos por período**, com `mask_scale=2`: cada faixa ocupa um pixel. Em ambos, o período é `2*mask_scale`. A intensidade mistura essa máscara com o sinal sem máscara; portanto a faixa chamada black é atenuada conforme a intensidade e fica totalmente preta apenas em intensidade 1. O preset suave usa a grille M/G, feixe mais largo e menos modulação.

Curvatura é zero por padrão. A opção positiva distorce somente a apresentação e pode ocultar cantos. As UVs do CRT são calculadas diretamente da posição física e do viewport com operações `precise`, evitando saltos de texel causados pela precisão da UV interpolada em curvatura.

## Parâmetros

Defina variáveis de ambiente antes de iniciar a sessão. Os nomes abaixo recebem o prefixo `MK1_CRT_`. O controlador os lê uma vez; mudar o ambiente depois não modifica a janela existente.

| Nome | Faixa inclusiva | 1080 | 4K | Suave |
|---|---:|---:|---:|---:|
| `SCANLINE_WEIGHT` | 0–1 | 0.85 | 0.85 | 0.62 |
| `BEAM_MIN_SIGMA` | 0.15–0.60 | 0.22 | 0.22 | 0.28 |
| `BEAM_MAX_SIGMA` | 0.15–0.60 | 0.40 | 0.40 | 0.46 |
| `MASK_INTENSITY` | 0–1 | 0.30 | 0.24 | 0.18 |
| `MASK_SCALE` | inteiros 1–4; RGB-black somente 2 ou 4 | 1 | 2 | 1 |
| `HORIZONTAL_SHARPNESS` | 0–1 | 0.65 | 0.65 | 0.65 |
| `HORIZONTAL_BLEND` | 0–0.5 | 0.12 | 0.12 | 0.18 |
| `HALATION_STRENGTH` | 0–0.15 | 0.035 | 0.035 | 0.055 |
| `GAMMA_IN` | 1–3 | 2.4 | 2.4 | 2.4 |
| `GAMMA_OUT` | 1–3 | 2.2 | 2.2 | 2.2 |
| `BRIGHTNESS_BOOST` | 1.2–1.35 | 1.28 | 1.28 | 1.25 |
| `CURVATURE` | 0–0.12 | 0 | 0 | 0 |

`BEAM_MIN_SIGMA` deve ser menor ou igual a `BEAM_MAX_SIGMA`. Maior sharpness estreita o kernel horizontal; seu sigma é `0.15 + 0.5*(1-sharpness)` texels. Os aliases `SCANLINE_STRENGTH`, `BEAM_MIN`, `BEAM_MAX`, `MASK_STRENGTH`, `HALATION` e `GAIN` são aceitos; quando ambos existem, o nome canônico da tabela vence. O JSON da apresentação registra os valores efetivos, alguns com esses nomes curtos, mais `MASK_PITCH` (período efetivo em pixels), dimensões da fonte e modo CRT.

A gramática aceita dígitos e um ponto decimal, sem espaços, sinais ou expoentes. NaN, infinito, vazio explicitamente definido, textos excedentes e valores fora da faixa falham com diagnóstico que identifica o parâmetro. Limites decimais são comparados em double antes da conversão para float, preservando os extremos 1.2 e 0.15.

Exemplo PowerShell:

```powershell
$env:MK1_CRT_SCANLINE_WEIGHT = '0.75'
$env:MK1_CRT_BRIGHTNESS_BOOST = '1.28'
.\MK1-TEMPORARIA-6.exe
# No SETTINGS, selecionar BVM 1080p, SALVAR e JOGAR.
```

## Verificação

`python tools/manual-temp-6-20261025/crt_check.py` compila contratos pequenos com MinGW `-std=c++17 -O2 -Wall -Wextra -Werror -DUNICODE -D_UNICODE` e vincula `d3d12`, `dxgi`, `d3dcompiler`, `dxguid`, `gdi32`. Não recompila o motor inteiro. Os binários usam um diretório temporário exclusivo e são removidos pelo guard de árvore, que verifica o caminho absoluto e rejeita links/junctions. Somente recibos JSON pequenos ficam no estágio.

O baseline real do renderer falhou nos três presets porque eles eram ignorados. O contrato final passou nos três padrões, 1920×1080, 3840×2160, janela 120×90, curvatura 0.05, overrides canônicos e preto integral. Cada cenário copiou a saída inteira da GPU para memória, incluindo margens e alpha, e comparou cada canal com referência escalar independente da amostragem HLSL. O erro máximo observado foi 1 byte; o limite é 3 para diferenças de cálculo/transcendentes, com **tolerância zero para canais cujo esperado é zero**. Preto integral teve erro máximo zero. Os seis contratos legados nearest/scanlines/linear/combined/default/invalid também passaram.

O controlador verifica 130 entradas inválidas, extremos inclusivos, relação entre sigmas, máscaras alinhadas, proporção/escala, janela mínima, overrides, preto zero e largura crescente do feixe. Na fixture independente, a relação cauda/centro do feixe, removida a gamma, foi 0.125589 para sinal escuro e 0.354708 para claro.

Recibos: `crt-baseline-red.json`, `crt-endpoint-red.json`, `crt-verification.json` e `crt-controller-verification.json`, no estágio `build/native/manual-temporary-6-20261025`. A verificação GPU integral registra o hash do controlador anterior à correção dos limites decimais; o shader e o código da janela correspondem ao final. A verificação separada do controlador registra o hash final e passou após essa correção. Nenhuma imagem, vídeo ou dump de pixels foi salvo; os recibos confirmam a remoção dos temporários. Os resultados são evidência dos testes realizados, não cópias de buffers já liberados.

A telemetria `draw_submit_fence_us` mede Close/ExecuteCommandLists/sinalização/espera da fence por QPC; exclui Present, conversão/referência CPU e o processamento do jogo. Na execução de contrato, a última submissão posterior à validação mediu 1056 µs em 1920×1080 e 1055 µs em 3840×2160. São amostras locais pequenas, sujeitas à carga de outros processos; a validação escalar completa, especialmente em 4K, é deliberadamente custosa. Esses números não são timestamps exclusivos da GPU nem um benchmark de FPS/latência do arcade.

A aparência é inspirada em monitores BVM e processadores CRT modernos. O modelo analítico de passagem única não certifica equivalência física com BVM, RetroTINK, PCB ou shaders multipasse. A resolução completa está de acordo com o [registro de correção 400×254 do MAME](https://mametesters.org/view.php?id=6509&nbn=4). O [preset CRT Guest Advanced](https://github.com/libretro/slang-shaders/blob/master/crt/crt-guest-advanced.slangp) é uma referência de arquitetura multipasse, sem código incorporado nem alegação de equivalência.
