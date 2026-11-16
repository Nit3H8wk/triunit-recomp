#pragma once
// The only launcher file that names the supported games: the compatibility list and the legal notice.
// Game names are plain text used to identify compatibility; no logo, art or other mark is used.
#include <array>
namespace mklauncher {
inline constexpr const wchar_t* productName=L"TriUnit Recomp";
inline constexpr const wchar_t* productTitle=L"TRIUNIT RECOMP";
// Index = launcher game index (0, 1, 2) and the setup id of tools/setup/setup.py.
struct CompatibleGame {const wchar_t* name;const wchar_t* revision;const wchar_t* setupId;};
inline constexpr std::array<CompatibleGame,4> compatibleGames{{
 {L"MORTAL KOMBAT",L"T-UNIT",L"mk1"},
 {L"MORTAL KOMBAT II",L"L3.1",L"mk2"},
 {L"MORTAL KOMBAT 3",L"REV 2.1",L"mk3"},
 {L"ULTIMATE MORTAL KOMBAT 3",L"",L"umk3"},
}};
inline constexpr std::array<const wchar_t*,3> legalNotice{{
 L"PROJETO INDEPENDENTE, SEM AFILIACAO COM WARNER BROS. ENTERTAINMENT INC. OU NETHERREALM STUDIOS.",
 L"NAO INCLUI ARQUIVOS DOS JOGOS: O CODIGO E GERADO NESTA MAQUINA A PARTIR DAS ROMS DO USUARIO.",
 L"NOMES DOS JOGOS USADOS SO PARA INDICAR COMPATIBILIDADE; MARCAS PERTENCEM AOS SEUS TITULARES.",
}};
}
