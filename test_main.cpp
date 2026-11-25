#include <iostream>
#include "platform_hal.h"
#include "renderer_hal.h"

using namespace triunit;

int main() {
    std::cout << "TriUnit Recomp - Linux Test Launcher" << std::endl;
    
    // Create renderer with window config
    gfx::WindowConfig cfg;
    cfg.title = "TriUnit Test";
    cfg.width = 640;
    cfg.height = 480;
    
    auto renderer = gfx::Renderer::create(cfg);
    if (!renderer.valid()) {
        std::cerr << "Failed to create renderer" << std::endl;
        return 1;
    }
    
    std::cout << "Renderer initialized successfully!" << std::endl;
    std::cout << "Press any key to exit..." << std::endl;
    
    // Simple loop - just keep the window open and present frames
    while (!renderer.should_close()) {
        renderer.begin_frame();
        renderer.end_frame();
        renderer.present();
    }
    
    std::cout << "Exiting cleanly." << std::endl;
    return 0;
}
