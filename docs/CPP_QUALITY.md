# Qualidade e testes C++

A prioridade é detectar regressões na tradução e apresentação do arcade.
Não criar regras próprias de dano, colisão, inventário ou IA para reproduzir
exemplos genéricos de testes. Os oráculos e fronteiras originais continuam
necessários; um teste rápido aprovado não substitui comparação com MAME/ROM.

## Comandos atuais

Executar na raiz com Python 3.13 e Windows. A suíte rápida usa o MinGW em
`C:/msys64/mingw64/bin/g++.exe`; pode-se passar `--compiler CAMINHO`.
Nenhuma dependência Python adicional é necessária para estes comandos.
Com `--sanitizer address`, o padrão é o Clang em
`C:/msys64/clang64/bin/clang++.exe`; o GCC de release permanece independente.

```powershell
python -B tools/quality/test_runner.py
python -B tools/quality/run.py fast
python -B tools/quality/run.py fast --sanitizer undefined
python -B tools/quality/run.py integration
python -B tools/quality/run.py smoke
python -B tools/quality/run.py headless
python -B tools/quality/run.py benchmark --repetitions 5
```

| Etapa | O que verifica | Requisitos |
|---|---|---|
| Testes do runner | falha/timeout, saída limitada, limpeza após exceção, recusa de resultado vazio e fronteira inválida | Python |
| `fast` | 17 contratos C++: controles/CRT/cor, PCM mono e estéreo, pacing, relógio, recursos de áudio, base/vídeo/PIXBLT/primitivas de boot MK2 e configuração persistida; testes Python dos verificadores MK2 | compilador, ROMs do usuário e saída do setup dos três jogos; sem GPU ou produto |
| `integration` | janela real, fullscreen e primeiro frame; DX12 real, readback em memória, blend e resize | compilador, desktop e GPU DX12 |
| `smoke` | launcher → sessão → motor → logger → encerramento, nos modos Original e Remasterizado, 113/127 frames | produto temporária 8, ROMs e áudio/GPU |
| `headless` | boot e main-loop limitados, progresso real, fronteira esperada e PCM completamente entregue | motor temporária 8, ROMs e dispositivo de áudio; sem janela |
| `benchmark` | 3–20 repetições da mesma carga headless, mediana de tempo/CPU e pico de working set | os mesmos de headless |

Os contratos são reaproveitados dos fontes atuais; não executar automaticamente
todos os scripts históricos. Alguns exigem dumps de referência apagados ou
produtos anteriores removidos. Ausência desses arquivos não autoriza afirmar
que uma comparação integral foi feita.

Integração também verifica os cinco passes ScaleFX na GPU: bordas, diagonais,
paleta original a 100%, mistura a 25% e saída original a 0%. A janela compartilhada
é verificada a 0/37/100%, com scanlines e CRT Energia, cor, brilho e moldura.
Readbacks ficam em memória. O oráculo de apresentação usa a saída intermediária
ScaleFX para conferir a composição; não constitui uma comparação integral do
algoritmo com outro emulador nem certificação de partidas completas.

Os comandos retornam **0 quando aprovados, 1 quando reprovados**. Erros de uso
da CLI retornam 2. Recibos por etapa em `build/native/quality/*.json`,
sobrescritos a cada execução. Incluem identidade do runner, compilador/fontes
nos contratos, binário/seed e argumentos na carga headless, resultados e limpeza.
Guardar um recibo junto ao commit avaliado quando for necessário preservar uma
baseline; o runner não declara equivalência com fontes a partir de um EXE antigo.

`smoke` usa a entrada diagnóstica do launcher: não automatiza cliques no menu
nem uma partida completa. Para esses fluxos, continua disponível
`python tools/mk1/product/check_flow.py` (requer `psutil`).
Não confundir o smoke com a qualificação de campanha/elenco.

## Ajustes de operador e launcher

```powershell
python -B tools/operator_settings_contract.py
python -B tools/quality/test_game_volume.py
python -B tools/operator_runtime_contract.py
```

Os contratos com ROMs usam perfis descartáveis e conferem a preservação integral
dos 16 KiB. Cobrem parâmetros/preços originais, ranking, conflitos de sessão,
CMOS antiga, rollback de INI, troca de instalação/perfil e independência das ROMs
publicadas do diretório de fontes. O oráculo MK1 executa as rotinas traduzidas de
CMOS/coinage/ranking; o MK2 confere os registros padrão com o seed autenticado.

Volume é conferido no sink real com WinMM simulado e controle negativo que ignora
o ganho. A matriz de sessões MK1 usa o produto instalado com CMOS descartável,
113 frames por caso, cinco dificuldades, quatro estados dos DIP de sangue/violência,
Free Play, Original/Remasterizada e presets CRT. Nenhum desses testes certifica
partidas completas ou o comportamento inteiro da IA em cada nível.

A integração GPU confere também PVM e todos os BVM com ScaleFX a 0/37/100%,
preservando o raster de entrada, além de geometria fullscreen após mudança de
monitor. As capturas de referência ficam em memória ou temporários removidos;
uma imagem pequena de revisão do launcher pode ser mantida.

## Memória, recursos e sanitizers

O novo contrato de ciclo de vida exercita o **sink real**, substituindo somente
a fronteira WinMM por falhas controladas. São 2.200 construções/destruições:
falha ao abrir, pausar ou preparar cada um dos oito headers, além de unwinding
com cauda PCM em memória. Dispositivos e headers devem voltar a zero; os eventos
Win32 reais devem retornar à contagem inicial em cada caso.
Isso detecta regressões de propriedade/liberação nessa classe. Não é uma
certificação de ausência de vazamentos em todo o processo, heap ou driver.

`--sanitizer undefined` compila a suíte rápida com checks UBSan em modo trap,
sem recuperação, excluindo `vptr` (exige runtime ausente nesse toolchain).
Um controle negativo de overflow deve ser detectado antes dos contratos.
O trap fornece falha imediata, com diagnóstico limitado; não instrumenta o
produto instalado nem todos os caminhos do motor.

ASan está configurado no ambiente separado **MSYS2 CLANG64**. A instalação
autorizada em 25/10/2026 adicionou Clang e compiler-rt 22.1.4-4. O pacote
oficial inclui `libclang_rt.asan_dynamic-x86_64.dll`; a distribuição GCC
MinGW continua sem `libasan` e não é usada para estes testes.

```powershell
# Uma vez, se CLANG64 não estiver instalado; requer MSYS2 em C:/msys64.
python -B tools/quality/setup_asan.py
# Repetível, sem instalar nada nem trocar o compilador do produto:
python -B tools/quality/run.py fast --sanitizer address
```

O instalador usa `pacman -S --needed` com cache exclusivo em `temporary-*`
do projeto e remove os downloads ao sair, inclusive em caso de erro. Na
instalação medida, removeu 131.129.074 bytes de cache. As ferramentas instaladas
(aproximadamente 904 MiB, incluindo dependências) permanecem em
`C:/msys64/clang64` para os próximos testes; não são dumps ou builds de teste.
Nenhuma mudança no PATH global é necessária. O recibo é
`build/native/quality/asan-toolchain-install.json`; a execução ASan fica em
`fast-address.json`, com identidade do compilador, runtime, fontes e limpeza.

O runner configura ASan para parar no primeiro erro e retornar 86, sem dumps,
logs em arquivo ou recuperação de erros. A saída é capturada em memória e
limitada. O compilador/runtime precisam iniciar e detectar um overflow de heap
deliberado antes dos sete contratos. Erros de loader, inicialização ou limpeza
não contam como detecção. O simbolizador tem até 0,5 s para encerrar após o
processo principal; descendentes que sobrevivem ao prazo reprovam e são encerrados.

Documentação da ferramenta: [CLANG64 no MinGW-w64](https://www.mingw-w64.org/getting-started/msys2-llvm/)
e [pacote compiler-rt no MSYS2](https://packages.msys2.org/packages/mingw-w64-clang-x86_64-compiler-rt).

ASan detecta classes de acesso inválido; LeakSanitizer não está disponível
neste alvo Windows (`detect_leaks=0` explícito). A aprovação não certifica
ausência de leaks no heap inteiro, drivers ou GPU. Referências oficiais:
[plataformas do LeakSanitizer](https://clang.llvm.org/docs/LeakSanitizer.html#supported-platforms),
[instrumentação GCC](https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html)
e [AddressSanitizer no MSVC](https://learn.microsoft.com/en-us/cpp/sanitizers/asan).
Não mascarar erros de sanitizers alterando o estado do arcade. Aritmética
intencional da CPU original exige representação C++ bem definida e prova própria.

## Performance e interpretação

### Compilação incremental do núcleo MK2

O runner reconhece as chamadas simples de GCC que compilam o núcleo grande
`mk2_task_batch.cpp` junto de outros fontes. Compila até duas unidades em
paralelo, conserva as flags e a ordem dos objetos no link e remove os objetos
temporários ao sair. Chamadas com opções não reconhecidas seguem o caminho
original. Não altera os fontes gerados nem o nível de otimização.

Para instalar explicitamente a ferramenta portátil e autenticada, sem alterar
o PATH global:

```powershell
python -B -m tools.quality.cpp_build --setup
python -B -m unittest tools.quality.test_cpp_build tools.mk2.test_build_identities
```

O ccache 4.14.2 fica em `build/toolchain/ccache-4.14.2`. Sem a ferramenta,
o runner compila em paralelo sem cache. O único cache compartilhado fica em
`build/native/compiler-cache`, com orçamento interno de 60 MB e verificação
do limite total de **64.000.000 bytes**, incluindo metadados. Essa retenção
de objetos foi autorizada pelo usuário em 04/11/2026. ROMs, estados do jogo,
áudio e imagens de teste não entram nesse cache.

Cada execução usa configuração isolada, ignora variáveis ambientes `CCACHE_*`,
desativa modo direto e não habilita tolerâncias de identidade. A chave considera
o conteúdo pré-processado, flags e identidade do compilador, `cc1plus` e assembler.
Mudanças de headers ou ferramentas invalidam os objetos correspondentes.
A limpeza do cache tem prazo próprio, inclusive após timeout da compilação.
Falhas de manutenção ou quota reprovam a execução.

O recibo do build informa unidades, hits/misses, bytes do cache e limpeza dos
temporários. Para uma medição de controle, a API `q.command` aceita
`parallel_cpp=False`, que executa a chamada monolítica original. Comparar
separadamente build frio e recompilação; um hit de cache não mede geração de
código, execução do jogo ou fidelidade. Referências:
[manual do ccache](https://ccache.dev/manual/latest.html) e
[dependências no GCC](https://gcc.gnu.org/onlinedocs/gcc/Preprocessor-Options.html).

Medição local de 04/11/2026, GCC 16.1.0, replay MK2 com as mesmas flags O1:

| Compilação e link | Amostras | Tempo |
|---|---:|---:|
| Chamada monolítica anterior | 1 | 100,78 s |
| Duas unidades em paralelo, cache vazio | 1 | 60,55 s |
| Recompilação, cache preenchido | 3 | mediana 11,36 s (11,33–11,50 s) |

Cada recompilação reutilizou 27 objetos e compilou o harness temporário novo.
O cache ocupava 3.495.257 bytes ao terminar essas medições; outras combinações
de flags podem ocupar mais, respeitando o mesmo limite. As cinco execuções
compararam novamente com MAME: 25 milhões de ciclos TMS, CPU34 final, seis
memórias completas, quatro rasters e todas as amostras DAC/speaker/PCM16,
além de roundtrip. Nenhuma diferença nesse cenário de quatro segundos.
Isso não certifica partidas completas. Recibos compactos locais em
`build/native/compile-cost-20261104/cache-benchmark.json` e `*-replay.json`;
capturas e executáveis de teste foram removidos. Os 113 arquivos de origem
e os executáveis de uso permaneceram idênticos.

O benchmark inclui boot, leitura de ROMs e drenagem de áudio real. Working set
é memória residente, não quantidade de alocações perdidas. CPU é tempo do
processo, não percentual de todo o computador. Comparar a mesma carga, binário,
seed, máquina e condições; executar sem compilação concorrente para uma baseline.
Não usar duração headless para anunciar FPS, consumo GPU ou suavidade visual.

O smoke registra os histogramas de cadência já expostos pelo produto e exige
zero underruns nas sessões medidas. Os histogramas têm resolução de 0,25 ms e
bucket de overflow: percentis são limites de buckets, não tempos exatos; o
máximo real continua disponível. O arcade permanece em aproximadamente
54,7069 Hz, independentemente da frequência de apresentação do monitor.
Não há orçamento universal de performance nem limiar de vazamento inventado.
Profiling GPU prolongado, sessões longas e todas as combinações de controles
permanecem verificações adicionais.

## Rotina recomendada

- A cada alteração relevante: runner + `fast`; em C++, também a instrumentação
  disponível. As compilações tratam `-Wall -Wextra` como erros.
- Ao tocar janela/renderização: `integration`; ao empacotar: `smoke` e o teste
  de fluxo apropriado. Mudanças em regras traduzidas exigem o oráculo original.
- Ao investigar regressão de custo: benchmark reproduzível e profiling dirigido,
  sem otimizar antes de medir ou sacrificar a cadência original.
- Manter RAII, proprietários explícitos e tipos não copiáveis onde já usados
  para handles/dispositivos. Não substituir ponteiros não proprietários por
  `shared_ptr` indiscriminadamente nem refatorar código gerado em massa.

O CI remoto (`.github/workflows/audit.yml`) roda só a guarda de publicação. A suíte `fast` precisa das ROMs do
usuário e da saída do setup e fica como gate local, com GPU e produto. Percentual de cobertura não foi
medido e não serve como substituto de cenários e oráculos relevantes.

## Armazenamento

Objetos reutilizáveis têm a exceção autorizada descrita acima: um único cache
de compilação com limite total de 64 MB e descarte automático.

Compilação e perfis de smoke somente em `temporary-quality-*` exclusivo sob
`build/native/quality`. Saída limitada em memória, sem vídeo/WAV/dump; a captura
DX12 é comparada em memória. Limpeza ao sair inclusive em falhas, com verificação
do caminho e recusa de symlinks/junctions. Processos Windows são iniciados
suspensos, associados a um Job Object próprio e então liberados para executar.
Timeouts e exceções encerram esse job inteiro, mesmo se o processo principal
já tiver saído; filhos restantes após o prazo de encerramento normal reprovam a etapa.
Se uma limpeza for bloqueada, a etapa reprova explicitamente. Não executar
com Python `-O`: o guard compartilhado usa assertions e o runner recusa esse modo.
Nunca apagar ROMs, assets de música, executáveis de uso ou seed CMOS de 16 KB.

## Resultado da primeira etapa em 25/10/2026 (antes do CLANG64)

10 testes do runner, 7 contratos normais e os mesmos 7 sob UBSan trap passaram;
o controle de overflow deliberado foi detectado. Integração: 2/2. Suíte smoke:
Original 113/Remasterizado 127 frames, zero underruns. Headless atingiu
`main-di-limit` 64. Cinco repetições isoladas da carga tiveram mediana 5,268 s,
CPU mediana 1,125 s e working set máximo 83,04 MiB. São medidas desta máquina/carga.
ASan falhou na verificação de suporte por ausência de `-lasan`.

Todos os recibos finais registraram limpeza concluída; zero árvores temporárias
de qualidade restantes. Foram preservados apenas os JSON compactos. Detalhes
atualizáveis estão em `build/native/quality`; esses resultados não certificam
todos os estados do arcade ou ausência de leaks em todo o programa.

## Atualização ASan em 25/10/2026

Clang/ASan 22.1.4: sete contratos aprovados, incluindo 2.200 ciclos de recursos
de áudio. Overflow deliberado detectado com diagnóstico `heap-buffer-overflow`
e exit 86. Treze testes do runner aprovados. Nenhum erro ASan encontrado nos
caminhos executados dos contratos; o overflow é exclusivamente o controle
negativo, não uma falha do produto. Não foi recompilado/substituído o motor
de uso nem executada uma campanha completa instrumentada.
