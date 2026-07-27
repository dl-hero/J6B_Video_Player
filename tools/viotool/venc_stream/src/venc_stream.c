/*
 * venc_stream.c — CIM4 四路视频流 H.264 编码 + TCP 输出
 *
 * 功能: 从 CIM4 的 DDR 缓冲区获取 YUV 帧 → VPU 硬件 H.264 编码 → 通过 hb_tool_server
 *       的 VIDEO_DATA 协议 TCP 发送到 PC 端。
 *
 * 复用模块:
 *   - camera_sample 的 VIO/CIM JSON 配置 (hb_vio_init + hb_cam_init)
 *   - libhbplayer 的 TCP Server (hb_tool_send_video_pic)
 *   - MediaCodec API 编码器 (参考 codec_sample)
 *
 * 部署: J6B 设备 /app/sample/S83_Sample/S83E04_Module/venc_stream/bin/
 *
 * 编译: 在 SDK 环境下 make, 依赖 libmultimedia + libhbplayer + libcam + libvio
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include <errno.h>
#include <getopt.h>

/* ---- SDK 头文件 ---- */
#include "hb_media_codec.h"      /* MediaCodec: hb_mm_mc_* */
#include "hb_media_error.h"
#include "hb_vin_data_info.h"     /* hb_cam_get_data / hb_cam_free_data */
#include "hb_vio_interface.h"     /* hb_vio_init / hb_vio_start_pipeline */
#include "hb_tool_server.h"       /* hb_tool_start_transfer / hb_tool_send_video_pic */

/* ======================================================================
 * 可配置参数 (按实际场景修改)
 * ====================================================================== */
#define CHANNEL_NUM      4           /* 编码通道数 */
#define ENC_WIDTH        1696        /* 图像宽度 */
#define ENC_HEIGHT       1168        /* 图像高度 */
#define ENC_FPS          30          /* 帧率 */
#define ENC_BITRATE      4000            /* 单路码率 4000 kbps = 4 Mbps CBR */
#define ENC_PIX_FMT      MC_PIXEL_FORMAT_NV12  /* H264 编码器仅支持 4:2:0 (NV12/420P/NV21) */
#define ENC_GOP_SIZE     ENC_FPS              /* I 帧间隔 1 秒 */

/* 调试日志: 改为 0 关闭, 1 开启 */
#define VENC_DEBUG       0

/* Pipeline ID 映射: vpm_config.json pipelineX 编号, 用于 hb_vio_start_pipeline(id) */
static const int PIPE_IDS[CHANNEL_NUM] = {7, 8, 9, 10};

/* CAM Port 映射: hb_j6dev.json port_X 编号, 用于 hb_cam_get_data(port, ...) */
static const int CAM_PORTS[CHANNEL_NUM] = {7, 8, 9, 10};

/*
 * 注意: ENC_PIX_FMT 需要与 CIM JSON 配置中的 format: 30 (YUV-8bit) 对应。
 * 如果 CIM 实际输出 YUV422, 可改为 MC_PIXEL_FORMAT_YUV422P。
 * VPU 硬件内部会将 YUV422 降采样为 4:2:0 再编码 (见手册 7.1.1 节)。
 */

/* ======================================================================
 * 每路编码通道上下文
 * ====================================================================== */
typedef struct {
    int              pipe_id;       /* pipeline 编号 (用于 hb_vio_start_pipeline) */
    int              cam_port;      /* CAM port 编号 (用于 hb_cam_get_data) */
    volatile int     running;       /* 运行标志 */
    volatile int     stream_end;    /* 码流结束标志 */

    media_codec_context_t enc_ctx;  /* VPU 编码器上下文 */
    int              poll_fd;       /* select() 等待编码完成的 fd */

    pthread_t        feed_tid;      /* 取帧线程 */
    pthread_t        output_tid;    /* 取码流+发送线程 */

    /* 统计 */
    uint64_t         frame_count;
    uint64_t         error_count;
#if VENC_DEBUG
    int              first_frame;  /* 首帧已打印 stride 信息 */
    uint64_t         feed_count;   /* feed 线程帧计数 */
#endif
} enc_channel_t;

/* ======================================================================
 * 全局变量
 * ====================================================================== */
static enc_channel_t  g_ch[CHANNEL_NUM];
static tool_event_t  *g_tool_ev = NULL;   /* hb_tool_server 事件句柄 */
static volatile int   g_quit = 0;
static int            g_no_init = 0;       /* 跳过 VIO/Cam 初始化 (复用已运行的VIO) */

/* 默认 JSON 配置文件路径 (可通过命令行参数覆盖) */
static const char *g_vio_cfg = "./vpm_config.json";
static const char *g_cam_cfg = "./hb_j6dev.json";

/* ======================================================================
 * 编码器初始化
 * 参照 codec_sample/src/sample.c 的 default_encode_task()
 * ====================================================================== */
static int init_encoder(enc_channel_t *ch)
{
    media_codec_context_t  *ctx = &ch->enc_ctx;
    mc_video_codec_enc_params_t *params;

    memset(ctx, 0, sizeof(*ctx));
    ctx->codec_id = MEDIA_CODEC_ID_H264;
    ctx->encoder  = 1;  /* TRUE */

    params = &ctx->video_enc_params;
    params->width               = ENC_WIDTH;
    params->height              = ENC_HEIGHT;
    params->pix_fmt             = ENC_PIX_FMT;
    params->frame_buf_count     = 3;  /* 低延迟: 3帧流水线 ≈ 100ms */
    params->bitstream_buf_count = 3;
    params->external_frame_buf  = 0;  /* 编码器分配内部 NV12 buffer */

    /* H.264 CBR 码率控制 — 先获取 FW 默认值再覆盖 */
    params->rc_params.mode = MC_AV_RC_MODE_H264CBR;
    hb_mm_mc_get_rate_control_config(ctx, &params->rc_params);
    params->rc_params.h264_cbr_params.intra_period   = ENC_FPS;
    params->rc_params.h264_cbr_params.intra_qp       = 30;
    params->rc_params.h264_cbr_params.bit_rate       = ENC_BITRATE;
    params->rc_params.h264_cbr_params.frame_rate     = ENC_FPS;
    params->rc_params.h264_cbr_params.initial_rc_qp  = 20;
    params->rc_params.h264_cbr_params.vbv_buffer_size = 300;   /* 低延迟: 300ms VBV ≈150KB, I帧~120KB安全 */
    params->rc_params.h264_cbr_params.min_qp_I       = 8;
    params->rc_params.h264_cbr_params.max_qp_I       = 50;
    params->rc_params.h264_cbr_params.min_qp_P       = 8;
    params->rc_params.h264_cbr_params.max_qp_P       = 50;
    params->rc_params.h264_cbr_params.min_qp_B       = 8;
    params->rc_params.h264_cbr_params.max_qp_B       = 50;
    params->rc_params.h264_cbr_params.hvs_qp_enable  = 1;
    params->rc_params.h264_cbr_params.hvs_qp_scale   = 2;
    params->rc_params.h264_cbr_params.max_delta_qp   = 10;
    params->rc_params.h264_cbr_params.qp_map_enable  = 0;

    /* GOP: I-P-P-P... (single reference, J6B 默认) */
    params->gop_params.decoding_refresh_type = 2;
    params->gop_params.gop_preset_idx = 9;

    params->rot_degree    = MC_CCW_0;
    params->mir_direction = MC_DIRECTION_NONE;
    params->frame_cropping_flag = 0;

    int ret;
    ret = hb_mm_mc_initialize(ctx);
    if (ret != 0) {
        fprintf(stderr, "Pipe %d: hb_mm_mc_initialize fail(%d)\n", ch->pipe_id, ret);
        return -1;
    }

    ret = hb_mm_mc_configure(ctx);
    if (ret != 0) {
        fprintf(stderr, "Pipe %d: hb_mm_mc_configure fail(%d)\n", ch->pipe_id, ret);
        return -1;
    }

    mc_av_codec_startup_params_t startup;
    memset(&startup, 0, sizeof(startup));
    startup.video_enc_startup_params.receive_frame_number = 0;
    ret = hb_mm_mc_start(ctx, &startup);
    if (ret != 0) {
        fprintf(stderr, "Pipe %d: hb_mm_mc_start fail(%d)\n", ch->pipe_id, ret);
        return -1;
    }

    ret = hb_mm_mc_get_fd(ctx, &ch->poll_fd);
    if (ret != 0) {
        fprintf(stderr, "Pipe %d: hb_mm_mc_get_fd fail(%d)\n", ch->pipe_id, ret);
        return -1;
    }

    printf("Pipe %d: encoder initialized (poll_fd=%d)\n", ch->pipe_id, ch->poll_fd);
    return 0;
}

static void release_encoder(enc_channel_t *ch)
{
    hb_mm_mc_stop(&ch->enc_ctx);
    hb_mm_mc_release(&ch->enc_ctx);
}

/* ======================================================================
 * 输出线程 (每路独立)
 * 循环: select poll_fd → deque output buffer → hb_tool_send_video_pic
 * ====================================================================== */
static void *output_thread(void *arg)
{
    enc_channel_t *ch = (enc_channel_t *)arg;
    media_codec_buffer_t           out_buf;
    media_codec_output_buffer_info_t info;
    pic_info_t                     pic_info;

    while (!ch->stream_end) {
        /* 等待编码器输出 */
        fd_set fds;
        struct timeval tv = { .tv_sec = 3, .tv_usec = 0 };
        FD_ZERO(&fds);
        FD_SET(ch->poll_fd, &fds);

        int ret = select(ch->poll_fd + 1, &fds, NULL, NULL, &tv);
        if (ret <= 0) {
            if (!ch->running) break;
            continue;
        }

        memset(&out_buf, 0, sizeof(out_buf));
        memset(&info,   0, sizeof(info));
        ret = hb_mm_mc_dequeue_output_buffer(&ch->enc_ctx, &out_buf, &info, 3000);
        if (ret == (int32_t)HB_MEDIA_ERR_WAIT_TIMEOUT)
            continue;
        if (ret != 0) {
            fprintf(stderr, "Pipe %d: dequeue output fail(%d / 0x%08X)\n",
                    ch->pipe_id, ret, (unsigned int)ret);
            break;
        }

        /*
         * 通过 libhbplayer 的 VIDEO_DATA 协议发送 H.264 码流。
         * 协议帧头 80 字节 (cmd_header_new_t) + 码流数据, 与 PC 端现有
         * hb_video_client.py 的接收逻辑兼容, 仅需 PC 端新增 VIDEO_DATA 分支。
         */
        memset(&pic_info, 0, sizeof(pic_info));
        pic_info.pipe_id   = (uint32_t)ch->pipe_id;
        pic_info.frame_id  = (uint32_t)out_buf.vstream_buf.pts;
        pic_info.type      = VIDEO_DATA;      /* DateType: 3 */
        pic_info.format    = YUVNV12;         /* YUV_TYEP: 复用此字段 */
        pic_info.width     = ENC_WIDTH;
        pic_info.height    = ENC_HEIGHT;
        pic_info.stride    = ENC_WIDTH;
        pic_info.code_type = H264;            /* VIDEO_TYPE: 0 */

        {
            int32_t send_ret = hb_tool_send_video_pic(g_tool_ev, &pic_info,
                               out_buf.vstream_buf.vir_ptr,
                               out_buf.vstream_buf.size);
#if VENC_DEBUG
            if (ch->frame_count % 100 == 0) {
                fprintf(stderr,
                    "[OUTPUT %2d] frame=%lu size=%u pts=%lu send_ret=%d\n",
                    ch->pipe_id, (unsigned long)ch->frame_count,
                    out_buf.vstream_buf.size,
                    (unsigned long)out_buf.vstream_buf.pts,
                    send_ret);
            }
#endif
            if (send_ret != 0) {
                fprintf(stderr, "Pipe %d: hb_tool_send_video_pic fail(%d)\n",
                    ch->pipe_id, send_ret);
            }
        }

        ch->frame_count++;

        if (out_buf.vstream_buf.stream_end)
            ch->stream_end = 1;

        hb_mm_mc_queue_output_buffer(&ch->enc_ctx, &out_buf, 100);
    }

    printf("Pipe %d: output thread exit (frames=%lu)\n",
           ch->pipe_id, (unsigned long)ch->frame_count);
    return NULL;
}

/* ======================================================================
 * 取帧线程 (每路独立)
 * 循环: hb_cam_get_data → dequeue input buffer → 填入地址 → queue input buffer
 * ====================================================================== */
static void *feed_thread(void *arg)
{
    enc_channel_t *ch = (enc_channel_t *)arg;
    media_codec_buffer_t in_buf;
    hb_vio_buffer_t      cam_buf;  /* hb_cam_get_data 返回的 buffer */
    int ret;

    while (ch->running) {
        /*
         * Step 1: 阻塞等待 CIM DDR 输出一帧数据。
         * HB_CAM_YUV_DATA 对应 CIM 的 ddr_enable=1 主通路 YUV 输出。
         */
        memset(&cam_buf, 0, sizeof(cam_buf));
        ret = hb_cam_get_data(ch->cam_port, HB_CAM_YUV_DATA, &cam_buf);
        if (ret != 0) {
            if (ch->running) {
                usleep(1000);  /* 1ms 后重试 */
                ch->error_count++;
            }
            continue;
        }

        /*
         * Step 2: 获取空闲的编码器输入 buffer。
         */
        memset(&in_buf, 0, sizeof(in_buf));
        ret = hb_mm_mc_dequeue_input_buffer(&ch->enc_ctx, &in_buf, 3000);
        if (ret != 0) {
            hb_cam_free_data(ch->cam_port, HB_CAM_YUV_DATA, &cam_buf);
            if (ret != (int32_t)HB_MEDIA_ERR_WAIT_TIMEOUT) {
                fprintf(stderr, "Pipe %d: dequeue input fail(%d / 0x%08X)\n",
                        ch->pipe_id, ret, (unsigned int)ret);
                ch->error_count++;
            }
            continue;
        }

        /*
         * Step 3: CIM NV12 → Encoder NV12 (逐行拷贝，处理 stride 对齐差异)
         * 编码器内部 buffer stride 可能对齐到 32/64/128，与 CIM stride(1696) 不同。
         */
        {
            uint8_t *src_y  = (uint8_t *)cam_buf.img_addr.addr[0];
            uint8_t *src_uv = (uint8_t *)cam_buf.img_addr.addr[1];
            uint8_t *dst_y  = in_buf.vframe_buf.vir_ptr[0];
            uint8_t *dst_uv = in_buf.vframe_buf.vir_ptr[1];
            int cim_stride  = cam_buf.img_addr.stride_size;
            int enc_stride  = in_buf.vframe_buf.stride;
            int w           = cam_buf.img_addr.width;
            int h           = cam_buf.img_addr.height;

            for (int r = 0; r < h; r++)
                memcpy(dst_y + r * enc_stride, src_y + r * cim_stride, w);
            for (int r = 0; r < h / 2; r++)
                memcpy(dst_uv + r * enc_stride, src_uv + r * cim_stride, w);
        }

        in_buf.vframe_buf.pts       = cam_buf.img_info.frame_id;
        in_buf.vframe_buf.frame_end = 0;

        hb_mm_mc_queue_input_buffer(&ch->enc_ctx, &in_buf, 100);

#if VENC_DEBUG
        ch->feed_count++;
        if (!ch->first_frame) {
            ch->first_frame = 1;
            fprintf(stderr,
                "[FEED   %2d] 首帧: CIM(stride=%u,w=%u,h=%u) → Enc(stride=%d) | "
                "size[0]=%u size[1]=%u\n",
                ch->pipe_id,
                cam_buf.img_addr.stride_size, cam_buf.img_addr.width, cam_buf.img_addr.height,
                in_buf.vframe_buf.stride,
                cam_buf.img_info.size[0], cam_buf.img_info.size[1]);
        }
        if (ch->feed_count % 100 == 0) {
            fprintf(stderr, "[FEED   %2d] queued %lu frames\n",
                ch->pipe_id, (unsigned long)ch->feed_count);
        }
#endif

        /*
         * Step 4: 归还 CIM buffer。
         */
        hb_cam_free_data(ch->cam_port, HB_CAM_YUV_DATA, &cam_buf);
    }

    printf("Pipe %d: feed thread exit\n", ch->pipe_id);
    return NULL;
}

/* ======================================================================
 * 信号处理
 * ====================================================================== */
static void sig_handler(int sig)
{
    (void)sig;
    printf("\nReceived exit signal, shutting down...\n");
    g_quit = 1;
}

/* ======================================================================
 * 使用帮助
 * ====================================================================== */
static void print_usage(const char *prog)
{
    printf("Usage: %s [OPTIONS]\n", prog);
    printf("Options:\n");
    printf("  -v, --vio-cfg <file>   VPM config JSON (default: ./vpm_config.json)\n");
    printf("  -c, --cam-cfg <file>   Camera config JSON (default: ./hb_j6dev.json)\n");
    printf("  -n, --no-init          Skip VIO/Camera init (reuse already running VIO)\n");
    printf("  -h, --help             Print this help\n");
    printf("\nExample:\n");
    printf("  %s -v ./cim4_4ch.json -c ./hb_j6dev.json\n", prog);
    printf("  %s -n  (skip init, use existing VIO)\n", prog);
}

/* ======================================================================
 * 主函数
 * ====================================================================== */
int main(int argc, char *argv[])
{
    int ret, opt;

    /* 解析命令行参数 */
    static const char short_opts[] = "v:c:nh";
    static const struct option long_opts[] = {
        { "vio-cfg", required_argument, NULL, 'v' },
        { "cam-cfg", required_argument, NULL, 'c' },
        { "no-init", no_argument,       NULL, 'n' },
        { "help",    no_argument,       NULL, 'h' },
        { NULL, 0, NULL, 0 },
    };

    while ((opt = getopt_long(argc, argv, short_opts, long_opts, NULL)) != -1) {
        switch (opt) {
        case 'v': g_vio_cfg = optarg; break;
        case 'c': g_cam_cfg = optarg; break;
        case 'n': g_no_init = 1; break;
        case 'h':
        default:  print_usage(argv[0]); return (opt == 'h') ? 0 : 1;
        }
    }

    signal(SIGINT,  sig_handler);
    signal(SIGTERM, sig_handler);

    printf("============================================================\n");
    printf("  J6B VENC Stream — 4-Channel H.264 Encoder + TCP Output\n");
    printf("============================================================\n");
    printf("  Resolution : %d × %d\n", ENC_WIDTH, ENC_HEIGHT);
    printf("  Frame rate : %d fps\n", ENC_FPS);
    printf("  Codec      : H.264 CBR %d kbps × %d ch\n",
           ENC_BITRATE, CHANNEL_NUM);
    printf("  Total BW   : ~%d kbps\n", ENC_BITRATE * CHANNEL_NUM);
    printf("  VIO config : %s\n", g_vio_cfg);
    printf("  Cam config : %s\n", g_cam_cfg);
    printf("============================================================\n\n");

    /*
     * ===== Phase 1: VIO + Camera 初始化 =====
     */
    if (g_no_init) {
        printf("[Phase 1/3] Skipping VIO/Camera init (reusing existing VIO)\n");
    } else {
        printf("[Phase 1/3] Initializing VIO + Camera ...\n");

        ret = hb_vio_init(g_vio_cfg);
        if (ret < 0) {
            fprintf(stderr, "ERROR: hb_vio_init(%s) = %d\n", g_vio_cfg, ret);
            return -1;
        }
        printf("  hb_vio_init() OK\n");

        ret = hb_cam_init(0, g_cam_cfg);
        if (ret < 0) {
            fprintf(stderr, "ERROR: hb_cam_init(%s) = %d\n", g_cam_cfg, ret);
            hb_vio_deinit();
            return -1;
        }
        printf("  hb_cam_init() OK\n");

        /* 启动所有 pipeline */
        for (int i = 0; i < CHANNEL_NUM; i++) {
            printf("  Starting pipeline %d ... ", PIPE_IDS[i]);
            ret = hb_vio_start_pipeline(PIPE_IDS[i]);
            if (ret < 0) {
                printf("FAIL(%d)\n", ret);
            } else {
                printf("OK\n");
            }
        }
    }

    /*
     * ===== Phase 2: 启动 TCP Server (libhbplayer) =====
     * 复用 hb_tool_server 的完整 TCP 协议栈。
     * PC 端用现有 hb_video_client.py 连接, 协议完全兼容。
     */
    printf("\n[Phase 2/3] Starting TCP server ...\n");

    g_tool_ev = hb_tool_start_transfer(DEFAULT_PORT);
    if (g_tool_ev == NULL) {
        fprintf(stderr, "ERROR: hb_tool_start_transfer(%d) failed\n", DEFAULT_PORT);
        hb_cam_deinit(0);
        hb_vio_deinit();
        return -1;
    }
    printf("  TCP server ready on port %d\n", DEFAULT_PORT);
    printf("  Waiting for PC client connection ...\n");

    /*
     * ===== Phase 3: 启动编码器 + 工作线程 =====
     */
    printf("\n[Phase 3/3] Starting %d encoders ...\n", CHANNEL_NUM);

    for (int i = 0; i < CHANNEL_NUM; i++) {
        memset(&g_ch[i], 0, sizeof(g_ch[i]));
        g_ch[i].pipe_id = PIPE_IDS[i];
        g_ch[i].cam_port = CAM_PORTS[i];
        g_ch[i].running = 1;

        if (init_encoder(&g_ch[i]) != 0) {
            fprintf(stderr, "FATAL: encoder %d init failed\n", i);
            for (int j = 0; j < i; j++) {
                g_ch[j].running = 0;
                pthread_join(g_ch[j].feed_tid, NULL);
                pthread_join(g_ch[j].output_tid, NULL);
                release_encoder(&g_ch[j]);
            }
            hb_tool_stop_transfer(g_tool_ev);
            hb_cam_deinit(0);
            hb_vio_deinit();
            return -1;
        }

        pthread_create(&g_ch[i].feed_tid,   NULL, feed_thread,   &g_ch[i]);
        pthread_create(&g_ch[i].output_tid, NULL, output_thread, &g_ch[i]);
        printf("  Pipe %d: encoder + threads started\n", i);
    }

    printf("\n"
           "  >>> Streaming 4-channel H.264 via TCP port %d <<<\n"
           "  Press Ctrl+C to stop.\n\n", DEFAULT_PORT);

    /*
     * ===== 主循环: 定期输出统计 =====
     */
    uint64_t prev_total = 0;
    while (!g_quit) {
        sleep(5);
        uint64_t total = 0, errors = 0;
#if VENC_DEBUG
        fprintf(stderr, "[STAT] ");
#endif
        for (int i = 0; i < CHANNEL_NUM; i++) {
            total  += g_ch[i].frame_count;
            errors += g_ch[i].error_count;
#if VENC_DEBUG
            fprintf(stderr, "ch%d:feed=%lu out=%lu err=%lu | ",
                g_ch[i].pipe_id,
                (unsigned long)g_ch[i].feed_count,
                (unsigned long)g_ch[i].frame_count,
                (unsigned long)g_ch[i].error_count);
#endif
        }
        uint64_t delta = total - prev_total;
        prev_total = total;
        printf("[STAT] Total frames: %lu | +%lu frames | ~%.1f fps | Errors: %lu\n",
               (unsigned long)total, (unsigned long)delta,
               (double)delta / 5.0, (unsigned long)errors);
#if VENC_DEBUG
        fprintf(stderr, "\n");
#endif
        /* 检查 TCP 连接状态 */
        if (g_tool_ev == NULL) {
            fprintf(stderr, "TCP connection lost, exiting.\n");
            g_quit = 1;
        }
    }

    /*
     * ===== 清理 =====
     */
    printf("\nCleaning up ...\n");

    for (int i = 0; i < CHANNEL_NUM; i++) {
        printf("  Stopping pipe %d ...\n", i);
        g_ch[i].running = 0;

        /* 等待线程退出 (最多 3 秒) */
        if (g_ch[i].feed_tid)
            pthread_join(g_ch[i].feed_tid, NULL);
        if (g_ch[i].output_tid)
            pthread_join(g_ch[i].output_tid, NULL);

        release_encoder(&g_ch[i]);
        printf("    frames=%lu errors=%lu\n",
               (unsigned long)g_ch[i].frame_count,
               (unsigned long)g_ch[i].error_count);
    }

    if (g_tool_ev) {
        hb_tool_stop_transfer(g_tool_ev);
        g_tool_ev = NULL;
    }

    if (!g_no_init) {
        for (int i = 0; i < CHANNEL_NUM; i++)
            hb_vio_stop_pipeline(PIPE_IDS[i]);
        hb_cam_deinit(0);
        hb_vio_deinit();
    }

    printf("Done. Goodbye.\n");
    return 0;
}
