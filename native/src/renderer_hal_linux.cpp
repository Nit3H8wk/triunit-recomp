// renderer_hal_linux.cpp — Vulkan 1.3 backend for Phase 3.
// Implements Dynamic Rendering, Synchronization2, and SDL3 window integration.
#include "renderer_hal.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_vulkan.h>
#include <vulkan/vulkan.h>
#include <vulkan/vulkan_core.h>
#include <cstring>
#include <vector>

namespace triunit::gfx {

struct Renderer::Impl {
    SDL_Window* window = nullptr;
    bool closed = false;
    int width = 640, height = 480;
    
    // Vulkan state
    VkInstance instance = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    uint32_t queue_family_index = 0;
    VkPhysicalDevice gpu = VK_NULL_HANDLE;
    
    // Swapchain images
    std::vector<VkImage> swapchain_images;
    std::vector<VkImageView> image_views;
    uint32_t current_image = 0;
    
    // Command buffers and pools
    VkCommandPool command_pool = VK_NULL_HANDLE;
    std::vector<VkCommandBuffer> command_buffers;
    
    // Synchronization
    std::vector<VkSemaphore> image_available_semaphores;
    std::vector<VkSemaphore> render_finished_semaphores;
    std::vector<VkFence> in_flight_fences;
    uint32_t frame_index = 0;
    
    // Pipeline
    VkPipeline pipeline = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout = VK_NULL_HANDLE;
    VkDescriptorSetLayout descriptor_set_layout = VK_NULL_HANDLE;
    VkDescriptorPool descriptor_pool = VK_NULL_HANDLE;
    std::vector<VkDescriptorSet> descriptor_sets;
    
    // Textures (game framebuffer, backdrop, overlay)
    struct Texture {
        VkImage image = VK_NULL_HANDLE;
        VkImageView view = VK_NULL_HANDLE;
        VkDeviceMemory memory = VK_NULL_HANDLE;
        uint32_t width = 0, height = 0;
    };
    Texture source_texture;
    Texture backdrop_texture;
    
    // Staging buffer for uploads
    VkBuffer staging_buffer = VK_NULL_HANDLE;
    VkDeviceMemory staging_memory = VK_NULL_HANDLE;
    
    // Uniform buffer for shader constants
    VkBuffer uniform_buffer = VK_NULL_HANDLE;
    VkDeviceMemory uniform_memory = VK_NULL_HANDLE;
    
    ~Impl() {
        cleanup_vulkan();
        if (window) SDL_DestroyWindow(window);
    }
    
    void cleanup_vulkan() {
        if (device) {
            vkDestroyDevice(device, nullptr);
            device = VK_NULL_HANDLE;
        }
        if (surface) {
            vkDestroySurfaceKHR(instance, surface, nullptr);
            surface = VK_NULL_HANDLE;
        }
        if (instance) {
            vkDestroyInstance(instance, nullptr);
            instance = VK_NULL_HANDLE;
        }
    }
    
    bool init_vulkan() {
        // Get Vulkan extensions from SDL3
        uint32_t extension_count = 0;
        const char* const* sdl_extensions = SDL_Vulkan_GetInstanceExtensions(&extension_count);
        
        std::vector<const char*> extensions(sdl_extensions, sdl_extensions + extension_count);
        
        // Create instance
        VkApplicationInfo app_info = {};
        app_info.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
        app_info.pApplicationName = "TriUnit Recomp";
        app_info.applicationVersion = VK_MAKE_VERSION(1, 0, 0);
        app_info.pEngineName = "TriUnit Engine";
        app_info.engineVersion = VK_MAKE_VERSION(1, 0, 0);
        app_info.apiVersion = VK_API_VERSION_1_3;
        
        VkInstanceCreateInfo instance_info = {};
        instance_info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
        instance_info.pApplicationInfo = &app_info;
        instance_info.enabledExtensionCount = extension_count;
        instance_info.ppEnabledExtensionNames = extensions.data();
        
        if (vkCreateInstance(&instance_info, nullptr, &instance) != VK_SUCCESS) {
            SDL_Log("Failed to create Vulkan instance");
            return false;
        }
        
        // Find suitable queue family
        uint32_t physical_device_count = 0;
        vkEnumeratePhysicalDevices(instance, &physical_device_count, nullptr);
        
        if (physical_device_count == 0) {
            SDL_Log("No Vulkan physical devices found");
            return false;
        }
        
        std::vector<VkPhysicalDevice> physical_devices(physical_device_count);
        vkEnumeratePhysicalDevices(instance, &physical_device_count, physical_devices.data());
        
        gpu = physical_devices[0];
        
        uint32_t queue_family_count = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &queue_family_count, nullptr);
        std::vector<VkQueueFamilyProperties> queue_families(queue_family_count);
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &queue_family_count, queue_families.data());
        
        for (uint32_t i = 0; i < queue_family_count; ++i) {
            if (queue_families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) {
                queue_family_index = i;
                break;
            }
        }
        
        // Create device
        float priority = 1.0f;
        VkDeviceQueueCreateInfo queue_info = {};
        queue_info.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
        queue_info.queueFamilyIndex = queue_family_index;
        queue_info.queueCount = 1;
        queue_info.pQueuePriorities = &priority;
        
        const char* device_extensions[] = {"VK_KHR_swapchain"};
        VkDeviceCreateInfo device_info = {};
        device_info.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
        device_info.queueCreateInfoCount = 1;
        device_info.pQueueCreateInfos = &queue_info;
        device_info.enabledExtensionCount = 1;
        device_info.ppEnabledExtensionNames = device_extensions;
        
        if (vkCreateDevice(gpu, &device_info, nullptr, &device) != VK_SUCCESS) {
            SDL_Log("Failed to create Vulkan device");
            return false;
        }
        
        vkGetDeviceQueue(device, queue_family_index, 0, &queue);
        
        // Create surface
        if (!SDL_Vulkan_CreateSurface(window, instance, nullptr, &surface)) {
            SDL_Log("Failed to create Vulkan surface");
            return false;
        }
        
        // Create swapchain
        create_swapchain();
        
        // Create command pool
        VkCommandPoolCreateInfo pool_info = {};
        pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pool_info.queueFamilyIndex = queue_family_index;
        vkCreateCommandPool(device, &pool_info, nullptr, &command_pool);
        
        // Create command buffers
        uint32_t image_count = swapchain_images.size();
        command_buffers.resize(image_count);
        VkCommandBufferAllocateInfo alloc_info = {};
        alloc_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        alloc_info.commandPool = command_pool;
        alloc_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        alloc_info.commandBufferCount = image_count;
        vkAllocateCommandBuffers(device, &alloc_info, command_buffers.data());
        
        // Create semaphores and fences
        image_available_semaphores.resize(image_count);
        render_finished_semaphores.resize(image_count);
        in_flight_fences.resize(image_count);
        
        VkSemaphoreCreateInfo semaphore_info = {};
        semaphore_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
        for (auto& sem : image_available_semaphores) {
            vkCreateSemaphore(device, &semaphore_info, nullptr, &sem);
        }
        for (auto& sem : render_finished_semaphores) {
            vkCreateSemaphore(device, &semaphore_info, nullptr, &sem);
        }
        
        VkFenceCreateInfo fence_info = {};
        fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        fence_info.flags = VK_FENCE_CREATE_SIGNALED_BIT;
        for (auto& fence : in_flight_fences) {
            vkCreateFence(device, &fence_info, nullptr, &fence);
        }
        
        // Create pipeline
        create_pipeline();
        
        return true;
    }
    
    void create_swapchain() {
        VkSurfaceCapabilitiesKHR capabilities;
        vkGetPhysicalDeviceSurfaceCapabilitiesKHR(gpu, surface, &capabilities);
        
        VkSwapchainCreateInfoKHR swapchain_info = {};
        swapchain_info.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
        swapchain_info.surface = surface;
        swapchain_info.minImageCount = capabilities.minImageCount;
        swapchain_info.imageFormat = VK_FORMAT_B8G8R8A8_SRGB;
        swapchain_info.imageColorSpace = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
        swapchain_info.imageExtent.width = width;
        swapchain_info.imageExtent.height = height;
        swapchain_info.imageArrayLayers = 1;
        swapchain_info.imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
        swapchain_info.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
        swapchain_info.preTransform = capabilities.currentTransform;
        swapchain_info.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
        swapchain_info.presentMode = VK_PRESENT_MODE_MAILBOX_KHR;
        swapchain_info.oldSwapchain = VK_NULL_HANDLE;
        
        if (vkCreateSwapchainKHR(device, &swapchain_info, nullptr, &swapchain) != VK_SUCCESS) {
            SDL_Log("Failed to create swapchain");
            return;
        }
        
        uint32_t image_count;
        vkGetSwapchainImagesKHR(device, swapchain, &image_count, nullptr);
        swapchain_images.resize(image_count);
        vkGetSwapchainImagesKHR(device, swapchain, &image_count, swapchain_images.data());
        
        image_views.resize(image_count);
        for (uint32_t i = 0; i < image_count; ++i) {
            VkImageViewCreateInfo view_info = {};
            view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
            view_info.image = swapchain_images[i];
            view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
            view_info.format = VK_FORMAT_B8G8R8A8_SRGB;
            view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
            view_info.subresourceRange.baseMipLevel = 0;
            view_info.subresourceRange.levelCount = 1;
            view_info.subresourceRange.baseArrayLayer = 0;
            view_info.subresourceRange.layerCount = 1;
            vkCreateImageView(device, &view_info, nullptr, &image_views[i]);
        }
    }
    
    void create_pipeline() {
        // Load SPIR-V shaders
        std::vector<uint32_t> vs_code, fs_code;
        load_spirv("build/spirv/test_vs.spv", vs_code);
        load_spirv("build/spirv/test_fs.spv", fs_code);
        
        VkShaderModuleCreateInfo vs_info = {};
        vs_info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        vs_info.codeSize = vs_code.size() * sizeof(uint32_t);
        vs_info.pCode = vs_code.data();
        VkShaderModule vs_module;
        vkCreateShaderModule(device, &vs_info, nullptr, &vs_module);
        
        VkShaderModuleCreateInfo fs_info = {};
        fs_info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        fs_info.codeSize = fs_code.size() * sizeof(uint32_t);
        fs_info.pCode = fs_code.data();
        VkShaderModule fs_module;
        vkCreateShaderModule(device, &fs_info, nullptr, &fs_module);
        
        // Create pipeline layout
        VkPipelineLayoutCreateInfo layout_info = {};
        layout_info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
        vkCreatePipelineLayout(device, &layout_info, nullptr, &pipeline_layout);
        
        // Create render pass (Dynamic Rendering - no legacy render pass needed)
        VkFormat color_format = VK_FORMAT_B8G8R8A8_SRGB;
        VkPipelineRenderingCreateInfo rendering_info = {};
        rendering_info.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO;
        rendering_info.colorAttachmentCount = 1;
        rendering_info.pColorAttachmentFormats = &color_format;
        
        VkGraphicsPipelineCreateInfo pipeline_info = {};
        pipeline_info.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
        pipeline_info.layout = pipeline_layout;
        pipeline_info.renderPass = VK_NULL_HANDLE; // Dynamic rendering
        pipeline_info.pNext = &rendering_info;
        
        VkPipelineShaderStageCreateInfo shader_stages[2] = {};
        shader_stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        shader_stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
        shader_stages[0].module = vs_module;
        shader_stages[0].pName = "main";
        
        shader_stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        shader_stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
        shader_stages[1].module = fs_module;
        shader_stages[1].pName = "main";
        
        pipeline_info.stageCount = 2;
        pipeline_info.pStages = shader_stages;
        
        VkPipelineVertexInputStateCreateInfo vertex_input = {};
        vertex_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
        pipeline_info.pVertexInputState = &vertex_input;
        
        VkPipelineInputAssemblyStateCreateInfo input_assembly = {};
        input_assembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
        input_assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
        pipeline_info.pInputAssemblyState = &input_assembly;
        
        VkPipelineViewportStateCreateInfo viewport_state = {};
        viewport_state.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
        viewport_state.viewportCount = 1;
        viewport_state.scissorCount = 1;
        pipeline_info.pViewportState = &viewport_state;
        
        VkPipelineRasterizationStateCreateInfo rasterizer = {};
        rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
        rasterizer.depthClampEnable = VK_FALSE;
        rasterizer.rasterizerDiscardEnable = VK_FALSE;
        rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
        rasterizer.lineWidth = 1.0f;
        pipeline_info.pRasterizationState = &rasterizer;
        
        VkPipelineMultisampleStateCreateInfo multisampling = {};
        multisampling.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
        multisampling.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
        pipeline_info.pMultisampleState = &multisampling;
        
        VkPipelineColorBlendAttachmentState blend_attachment = {};
        blend_attachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
        VkPipelineColorBlendStateCreateInfo color_blending = {};
        color_blending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
        color_blending.attachmentCount = 1;
        color_blending.pAttachments = &blend_attachment;
        pipeline_info.pColorBlendState = &color_blending;
        
        if (vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1, &pipeline_info, nullptr, &pipeline) != VK_SUCCESS) {
            SDL_Log("Failed to create pipeline");
        }
        
        vkDestroyShaderModule(device, vs_module, nullptr);
        vkDestroyShaderModule(device, fs_module, nullptr);
    }
    
    VkFormat swapchain_info_format() {
        return VK_FORMAT_B8G8R8A8_SRGB;
    }
    
    void load_spirv(const char* path, std::vector<uint32_t>& code) {
        FILE* file = fopen(path, "rb");
        if (!file) {
            SDL_Log("Failed to open SPIR-V file: %s", path);
            return;
        }
        fseek(file, 0, SEEK_END);
        long size = ftell(file);
        fseek(file, 0, SEEK_SET);
        
        code.resize(size / sizeof(uint32_t));
        fread(code.data(), sizeof(uint32_t), code.size(), file);
        fclose(file);
    }
    
    void create_descriptor_set_layout() {
        VkDescriptorSetLayoutBinding bindings[4] = {};
        
        // Binding 0: Source texture (sampled image)
        bindings[0].binding = 0;
        bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        bindings[0].descriptorCount = 1;
        bindings[0].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
        
        // Binding 1: Backdrop texture (sampled image)
        bindings[1].binding = 1;
        bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        bindings[1].descriptorCount = 1;
        bindings[1].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
        
        // Binding 2: Overlay texture (sampled image)
        bindings[2].binding = 2;
        bindings[2].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        bindings[2].descriptorCount = 1;
        bindings[2].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
        
        // Binding 3: Uniform buffer (shader constants)
        bindings[3].binding = 3;
        bindings[3].descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
        bindings[3].descriptorCount = 1;
        bindings[3].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
        
        VkDescriptorSetLayoutCreateInfo layout_info = {};
        layout_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
        layout_info.bindingCount = 4;
        layout_info.pBindings = bindings;
        
        vkCreateDescriptorSetLayout(device, &layout_info, nullptr, &descriptor_set_layout);
    }
    
    void create_descriptor_pool() {
        VkDescriptorPoolSize pool_sizes[2] = {};
        pool_sizes[0].type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        pool_sizes[0].descriptorCount = 16;
        pool_sizes[1].type = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
        pool_sizes[1].descriptorCount = 16;
        
        VkDescriptorPoolCreateInfo pool_info = {};
        pool_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
        pool_info.maxSets = 16;
        pool_info.poolSizeCount = 2;
        pool_info.pPoolSizes = pool_sizes;
        
        vkCreateDescriptorPool(device, &pool_info, nullptr, &descriptor_pool);
    }
    
    void create_staging_buffer(VkDeviceSize size) {
        VkBufferCreateInfo buffer_info = {};
        buffer_info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        buffer_info.size = size;
        buffer_info.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
        buffer_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        
        vkCreateBuffer(device, &buffer_info, nullptr, &staging_buffer);
        
        VkMemoryRequirements mem_requirements;
        vkGetBufferMemoryRequirements(device, staging_buffer, &mem_requirements);
        
        VkMemoryAllocateInfo alloc_info = {};
        alloc_info.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        alloc_info.allocationSize = mem_requirements.size;
        alloc_info.memoryTypeIndex = find_memory_type(mem_requirements.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        
        vkAllocateMemory(device, &alloc_info, nullptr, &staging_memory);
        vkBindBufferMemory(device, staging_buffer, staging_memory, 0);
    }
    
    uint32_t find_memory_type(uint32_t type_filter, VkMemoryPropertyFlags properties) {
        VkPhysicalDeviceMemoryProperties mem_properties;
        vkGetPhysicalDeviceMemoryProperties(gpu, &mem_properties);
        
        for (uint32_t i = 0; i < mem_properties.memoryTypeCount; ++i) {
            if ((type_filter & (1 << i)) && (mem_properties.memoryTypes[i].propertyFlags & properties) == properties) {
                return i;
            }
        }
        return 0;
    }
    
    void upload_texture(Texture& tex, const uint8_t* data, uint32_t width, uint32_t height) {
        // Create image
        VkImageCreateInfo image_info = {};
        image_info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        image_info.imageType = VK_IMAGE_TYPE_2D;
        image_info.format = VK_FORMAT_R8G8B8A8_UNORM;
        image_info.extent.width = width;
        image_info.extent.height = height;
        image_info.extent.depth = 1;
        image_info.mipLevels = 1;
        image_info.arrayLayers = 1;
        image_info.samples = VK_SAMPLE_COUNT_1_BIT;
        image_info.tiling = VK_IMAGE_TILING_OPTIMAL;
        image_info.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        image_info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        
        vkCreateImage(device, &image_info, nullptr, &tex.image);
        
        VkMemoryRequirements mem_requirements;
        vkGetImageMemoryRequirements(device, tex.image, &mem_requirements);
        
        VkMemoryAllocateInfo alloc_info = {};
        alloc_info.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        alloc_info.allocationSize = mem_requirements.size;
        alloc_info.memoryTypeIndex = find_memory_type(mem_requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        
        vkAllocateMemory(device, &alloc_info, nullptr, &tex.memory);
        vkBindImageMemory(device, tex.image, tex.memory, 0);
        
        // Create image view
        VkImageViewCreateInfo view_info = {};
        view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
        view_info.image = tex.image;
        view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
        view_info.format = VK_FORMAT_R8G8B8A8_UNORM;
        view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        view_info.subresourceRange.baseMipLevel = 0;
        view_info.subresourceRange.levelCount = 1;
        view_info.subresourceRange.baseArrayLayer = 0;
        view_info.subresourceRange.layerCount = 1;
        
        vkCreateImageView(device, &view_info, nullptr, &tex.view);
        
        // Upload data via staging buffer
        VkDeviceSize size = width * height * 4;
        if (staging_buffer == VK_NULL_HANDLE) {
            create_staging_buffer(size);
        }
        
        void* dst;
        vkMapMemory(device, staging_memory, 0, size, 0, &dst);
        memcpy(dst, data, size);
        vkUnmapMemory(device, staging_memory);
        
        // Copy from staging buffer to image
        VkCommandBuffer cmd;
        VkCommandBufferAllocateInfo alloc_info_cmd = {};
        alloc_info_cmd.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        alloc_info_cmd.commandPool = command_pool;
        alloc_info_cmd.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        alloc_info_cmd.commandBufferCount = 1;
        vkAllocateCommandBuffers(device, &alloc_info_cmd, &cmd);
        
        VkCommandBufferBeginInfo begin_info = {};
        begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        vkBeginCommandBuffer(cmd, &begin_info);
        
        VkImageMemoryBarrier barrier = {};
        barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        barrier.srcAccessMask = 0;
        barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.image = tex.image;
        barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        barrier.subresourceRange.baseMipLevel = 0;
        barrier.subresourceRange.levelCount = 1;
        barrier.subresourceRange.baseArrayLayer = 0;
        barrier.subresourceRange.layerCount = 1;
        
        vkCmdPipelineBarrier(cmd, 0, VK_ACCESS_TRANSFER_WRITE_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
        
        VkBufferImageCopy region = {};
        region.bufferOffset = 0;
        region.bufferRowLength = 0;
        region.bufferImageHeight = 0;
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.imageSubresource.mipLevel = 0;
        region.imageSubresource.baseArrayLayer = 0;
        region.imageSubresource.layerCount = 1;
        region.imageOffset.x = 0;
        region.imageOffset.y = 0;
        region.imageOffset.z = 0;
        region.imageExtent.width = width;
        region.imageExtent.height = height;
        region.imageExtent.depth = 1;
        
        vkCmdCopyBufferToImage(cmd, staging_buffer, tex.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
        
        // Transition to shader read optimal
        barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
        barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        
        vkCmdPipelineBarrier(cmd, VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
        
        vkEndCommandBuffer(cmd);
        
        VkSubmitInfo submit_info = {};
        submit_info.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit_info.commandBufferCount = 1;
        submit_info.pCommandBuffers = &cmd;
        vkQueueSubmit(queue, 1, &submit_info, VK_NULL_HANDLE);
        vkQueueWaitIdle(queue);
        
        vkFreeCommandBuffers(device, command_pool, 1, &cmd);
    }
    
    void update_uniform_buffer(const float* constants, size_t count) {
        VkDeviceSize size = count * sizeof(float);
        if (uniform_buffer == VK_NULL_HANDLE) {
            VkBufferCreateInfo buffer_info = {};
            buffer_info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
            buffer_info.size = size;
            buffer_info.usage = VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT;
            buffer_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
            
            vkCreateBuffer(device, &buffer_info, nullptr, &uniform_buffer);
            
            VkMemoryRequirements mem_requirements;
            vkGetBufferMemoryRequirements(device, uniform_buffer, &mem_requirements);
            
            VkMemoryAllocateInfo alloc_info = {};
            alloc_info.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
            alloc_info.allocationSize = mem_requirements.size;
            alloc_info.memoryTypeIndex = find_memory_type(mem_requirements.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
            
            vkAllocateMemory(device, &alloc_info, nullptr, &uniform_memory);
            vkBindBufferMemory(device, uniform_buffer, uniform_memory, 0);
        }
        
        void* dst;
        vkMapMemory(device, uniform_memory, 0, size, 0, &dst);
        memcpy(dst, constants, size);
        vkUnmapMemory(device, uniform_memory);
    }
    
    void begin_frame() {
        uint32_t frame_index = this->frame_index % in_flight_fences.size();
        
        vkWaitForFences(device, 1, &in_flight_fences[frame_index], VK_TRUE, UINT64_MAX);
        vkResetFences(device, 1, &in_flight_fences[frame_index]);
        
        VkResult result;
        uint32_t image_index;
        result = vkAcquireNextImageKHR(device, swapchain, UINT64_MAX, image_available_semaphores[frame_index], VK_NULL_HANDLE, &image_index);
        
        if (result == VK_ERROR_OUT_OF_DATE_KHR || result == VK_SUBOPTIMAL_KHR) {
            // Resize will be handled by the Renderer::resize() method
            return;
        }
        
        current_image = image_index;
    }
    
    void record_command_buffer(VkCommandBuffer cmd) {
        VkCommandBufferBeginInfo begin_info = {};
        begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        vkBeginCommandBuffer(cmd, &begin_info);
        
        // Dynamic rendering
        VkClearValue clear_value = {};
        clear_value.color.float32[0] = 0.1f;
        clear_value.color.float32[1] = 0.1f;
        clear_value.color.float32[2] = 0.1f;
        clear_value.color.float32[3] = 1.0f;
        
        VkRenderingAttachmentInfo color_attachment = {};
        color_attachment.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;
        color_attachment.imageView = image_views[current_image];
        color_attachment.imageLayout = VK_IMAGE_LAYOUT_GENERAL;
        color_attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
        color_attachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
        color_attachment.clearValue = clear_value;
        
        VkRenderingInfo rendering_info = {};
        rendering_info.sType = VK_STRUCTURE_TYPE_RENDERING_INFO;
        rendering_info.renderArea.offset.x = 0;
        rendering_info.renderArea.offset.y = 0;
        rendering_info.renderArea.extent.width = width;
        rendering_info.renderArea.extent.height = height;
        rendering_info.layerCount = 1;
        rendering_info.colorAttachmentCount = 1;
        rendering_info.pColorAttachments = &color_attachment;
        
        vkCmdBeginRendering(cmd, &rendering_info);
        
        // Bind pipeline
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);
        
        // Set viewport and scissor
        VkViewport viewport = {};
        viewport.width = (float)width;
        viewport.height = (float)height;
        viewport.minDepth = 0.0f;
        viewport.maxDepth = 1.0f;
        vkCmdSetViewport(cmd, 0, 1, &viewport);
        
        VkRect2D scissor = {};
        scissor.offset.x = 0;
        scissor.offset.y = 0;
        scissor.extent.width = width;
        scissor.extent.height = height;
        vkCmdSetScissor(cmd, 0, 1, &scissor);
        
        // Draw fullscreen triangle
        vkCmdDraw(cmd, 3, 1, 0, 0);
        
        vkCmdEndRendering(cmd);
        
        vkEndCommandBuffer(cmd);
    }
    
    void end_frame() {
        uint32_t frame_index = this->frame_index % in_flight_fences.size();
        
        VkSubmitInfo submit_info = {};
        submit_info.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit_info.waitSemaphoreCount = 1;
        submit_info.pWaitSemaphores = &image_available_semaphores[frame_index];
        submit_info.commandBufferCount = 1;
        submit_info.pCommandBuffers = &command_buffers[current_image];
        submit_info.signalSemaphoreCount = 1;
        submit_info.pSignalSemaphores = &render_finished_semaphores[frame_index];
        
        vkQueueSubmit(queue, 1, &submit_info, in_flight_fences[frame_index]);
        
        VkPresentInfoKHR present_info = {};
        present_info.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
        present_info.waitSemaphoreCount = 1;
        present_info.pWaitSemaphores = &render_finished_semaphores[frame_index];
        present_info.swapchainCount = 1;
        present_info.pSwapchains = &swapchain;
        present_info.pImageIndices = &current_image;
        
        VkResult result = vkQueuePresentKHR(queue, &present_info);
        if (result == VK_ERROR_OUT_OF_DATE_KHR || result == VK_SUBOPTIMAL_KHR) {
            // Resize will be handled by the Renderer::resize() method
        }
        
        this->frame_index++;
    }
};

Renderer::Renderer() : impl(new Impl()) {}
Renderer::~Renderer() { impl.reset(); }
Renderer::Renderer(Renderer&& other) noexcept : impl(std::move(other.impl)) {}
Renderer& Renderer::operator=(Renderer&& other) noexcept { 
    if (this != &other) impl = std::move(other.impl); 
    return *this; 
}

Renderer Renderer::create(const WindowConfig& cfg) {
    Renderer r;
    if (!SDL_Init(SDL_INIT_VIDEO)) {
        SDL_Log("Failed to initialize SDL3: %s", SDL_GetError());
        return r;
    }
    
    Uint32 flags = SDL_WINDOW_RESIZABLE | SDL_WINDOW_VULKAN;
    if (cfg.fullscreen) flags |= SDL_WINDOW_FULLSCREEN;
    
    r.impl->window = SDL_CreateWindow(cfg.title, cfg.width, cfg.height, flags);
    if (!r.impl->window) {
        SDL_Log("Failed to create window: %s", SDL_GetError());
        SDL_Quit();
        return r;
    }
    
    r.impl->width = cfg.width;
    r.impl->height = cfg.height;
    
    if (!r.impl->init_vulkan()) {
        SDL_Log("Failed to initialize Vulkan");
        SDL_DestroyWindow(r.impl->window);
        r.impl->window = nullptr;
        SDL_Quit();
        return r;
    }
    
    return r;
}

void Renderer::resize(int width, int height) {
    if (impl->window && impl->device) {
        // Wait for device to be idle before recreating swapchain
        vkDeviceWaitIdle(impl->device);
        
        // Clean up old swapchain resources
        for (auto view : impl->image_views) {
            vkDestroyImageView(impl->device, view, nullptr);
        }
        if (impl->swapchain) {
            vkDestroySwapchainKHR(impl->device, impl->swapchain, nullptr);
        }
        
        impl->width = width;
        impl->height = height;
        impl->create_swapchain();
    }
}

void Renderer::present() {
    if (impl->device && impl->swapchain) {
        impl->begin_frame();
        impl->record_command_buffer(impl->command_buffers[impl->current_image]);
        impl->end_frame();
    } else {
        SDL_Delay(16); // ~60 FPS cap for non-Vulkan mode
    }
}

uint32_t Renderer::create_texture(const TextureConfig&) { return 0; }
void Renderer::destroy_texture(uint32_t) {}
void Renderer::upload_texture(uint32_t, const uint8_t*, size_t) {}
uint32_t Renderer::create_pipeline(const RenderPassDesc&) { return 0; }
void Renderer::destroy_pipeline(uint32_t) {}
void Renderer::begin_frame() {}
void Renderer::bind_pipeline(uint32_t) {}
void Renderer::bind_texture(int, uint32_t) {}
void Renderer::set_uniforms(const float*, size_t) {}
void Renderer::draw_fullscreen_quad() {}
void Renderer::end_frame() {}
void Renderer::set_hdr_metadata(float, float) {}
void Renderer::set_srgb_output(bool) {}

void Renderer::set_window(void* sdl_window) {
    impl->window = static_cast<SDL_Window*>(sdl_window);
}

bool Renderer::should_close() {
    if (impl->closed) return true;
    
    SDL_Event event;
    while (SDL_PollEvent(&event)) {
        switch (event.type) {
            case SDL_EVENT_QUIT:
                impl->closed = true;
                return true;
            case SDL_EVENT_WINDOW_RESIZED:
                resize(event.window.data1, event.window.data2);
                break;
            case SDL_EVENT_KEY_DOWN:
                if (event.key.key == SDLK_ESCAPE) {
                    impl->closed = true;
                    return true;
                }
                break;
            default:
                break;
        }
    }
    return false;
}

bool Renderer::valid() const {
    return impl && !impl->closed && impl->window != nullptr;
}

} // namespace triunit::gfx
