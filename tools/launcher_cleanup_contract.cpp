// The same App scope used by wWinMain, with a deliberately thrown exception.
#include "../native/launcher/launcher_main.cpp"
#include <iostream>
int main(int argc,char** argv){
    if(argc!=2&&argc!=3)return 2;
    auto root=fs::u8path(argv[1]);
    if(argc==3){App app(root);app.key(VK_RETURN);if(app.mk1Available||app.notice.find(L"ROMs")==std::wstring::npos)return 5;app.act(20);if(app.backend.running())return 6;std::cout<<"{\"passed\":true,\"missing_rom_visible_error\":true,\"missing_rom_cannot_start\":true}\n";return 0;}
    try{
        App app(root);app.focus=0;app.key(VK_RETURN);
        if(app.chosen!=0||app.details||app.backend.running())throw std::runtime_error("selection must remain separate from Play");
        if(!app.mk1Available)throw std::runtime_error("copied install is unavailable");
        app.key(VK_DOWN);app.key(VK_RETURN);
        if(!app.backend.running())throw std::runtime_error("cleanup test could not launch through Play");
        const auto end=GetTickCount64()+20000;while(!app.backend.gameWindow()&&GetTickCount64()<end){app.backend.poll();Sleep(50);}
        if(!app.backend.gameWindow())throw std::runtime_error("cleanup test game did not become visible");
        throw std::runtime_error("intentional launcher exception");
    }catch(const std::exception& e){
        if(std::string(e.what())!="intentional launcher exception"){std::cerr<<e.what();return 3;}
    }
    std::cout<<"{\"passed\":true,\"app_exception_cleanup_returned\":true,\"selection_and_play_separate\":true}\n";
}
