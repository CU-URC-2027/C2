/* Experimental video media worker. stdin: >QQI PTS, source sequence, NV12 bytes.
 * stdout: >II JSON length, payload length, JSON, payload. No network/file sink.
 * Control fd: RATE <bps> <revision>, PREVIEW 0|1, KEYFRAME, QUIT.
 */
#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video-event.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <errno.h>
#include <poll.h>

static GstElement *pipeline, *input, *encoder, *preview_pipeline, *preview_input;
static GMainLoop *loop;
static GMutex output_lock, preview_lock, settings_lock;
static guint width_out, height_out, fps_out, requested_bps;
static guint64 applied_revision;
static gint stopping;
static gboolean preview_needs_keyframe=TRUE;
static guint preview_bus_watch;
static const char *factory;
static gboolean preview_set(gpointer value);

static gboolean read_all(int fd, void *buffer, size_t size) {
  char *p=buffer; while(size) {
    if(g_atomic_int_get(&stopping))return FALSE;
    struct pollfd ready={fd,POLLIN,0};int result=poll(&ready,1,100);
    if(result==0||(result<0&&errno==EINTR))continue;
    if(result<0)return FALSE;
    ssize_t n=read(fd,p,size); if(n<0&&errno==EINTR)continue;
    if(n<=0)return FALSE; p+=n;size-=n; } return TRUE;
}
static gboolean write_all(int fd, const void *buffer, size_t size) {
  const char *p=buffer;while(size){ssize_t n=write(fd,p,size);if(n<0&&errno==EINTR)continue;
    if(n<=0)return FALSE;p+=n;size-=n;}return TRUE;
}
static void emit(const char *json, const void *payload, guint32 size) {
  guint32 header[2]={GUINT32_TO_BE(strlen(json)),GUINT32_TO_BE(size)};
  g_mutex_lock(&output_lock);
  gboolean ok=write_all(1,header,8)&&write_all(1,json,strlen(json))&&(!size||write_all(1,payload,size));
  g_mutex_unlock(&output_lock);if(!ok){g_atomic_int_set(&stopping,1);g_main_loop_quit(loop);}
}
static void message(const char *type, const char *text) {
  GString *escaped=g_string_new(NULL);
  for(const unsigned char *p=(const unsigned char *)(text?text:"");*p;p++){
    if(*p=='"'||*p=='\\')g_string_append_c(escaped,'\\');
    if(*p<32)g_string_append_printf(escaped,"\\u%04x",*p);
    else g_string_append_c(escaped,*p);
  }
  char *json=g_strdup_printf("{\"type\":\"%s\",\"message\":\"%s\"}",type,escaped->str);
  emit(json,NULL,0);g_free(json);g_string_free(escaped,TRUE);
}
static void force_keyframe(void) {
  GstPad *pad=gst_element_get_static_pad(encoder,"src");
  gst_pad_send_event(pad,gst_video_event_new_upstream_force_key_unit(GST_CLOCK_TIME_NONE,TRUE,0));
  gst_object_unref(pad);
}
static gboolean on_bus(GstBus *bus, GstMessage *msg, gpointer data) {
  (void)bus;(void)data;
  if(GST_MESSAGE_TYPE(msg)==GST_MESSAGE_ERROR){GError *e=NULL;char *debug=NULL;
    gst_message_parse_error(msg,&e,&debug);message("error",e->message);g_clear_error(&e);g_free(debug);
    g_atomic_int_set(&stopping,1);g_main_loop_quit(loop);
  } return TRUE;
}
static gboolean on_preview_bus(GstBus *bus, GstMessage *msg, gpointer data) {
  (void)bus;(void)data;
  if(GST_MESSAGE_TYPE(msg)==GST_MESSAGE_ERROR){
    GError *e=NULL;char *debug=NULL;gst_message_parse_error(msg,&e,&debug);
    message("preview_error",e->message);g_clear_error(&e);g_free(debug);
    preview_bus_watch=0;preview_set(GINT_TO_POINTER(0));return G_SOURCE_REMOVE;
  }return G_SOURCE_CONTINUE;
}
static GstFlowReturn on_preview(GstAppSink *sink, gpointer data) {
  (void)data;GstSample *sample=gst_app_sink_pull_sample(sink);if(!sample)return GST_FLOW_EOS;
  GstBuffer *b=gst_sample_get_buffer(sample);GstMapInfo map;
  if(gst_buffer_map(b,&map,GST_MAP_READ)){
    char *json=g_strdup_printf("{\"type\":\"preview\",\"pts_ns\":%"G_GUINT64_FORMAT",\"width\":480,\"height\":270}",GST_BUFFER_PTS(b));
    emit(json,map.data,map.size);g_free(json);gst_buffer_unmap(b,&map);
  }gst_sample_unref(sample);return GST_FLOW_OK;
}
static gboolean has_idr(const guint8 *data,gsize size) {
  for(gsize i=0;i+3<size;i++)
    if(data[i]==0&&data[i+1]==0&&data[i+2]==1&&(data[i+3]&31)==5)return TRUE;
  return FALSE;
}
static GstFlowReturn on_encoded(GstAppSink *sink, gpointer data) {
  (void)data;GstSample *sample=gst_app_sink_pull_sample(sink);if(!sample)return GST_FLOW_EOS;
  GstBuffer *b=gst_sample_get_buffer(sample);GstMapInfo map;
  GstCaps *caps=gst_sample_get_caps(sample);GstStructure *s=gst_caps_get_structure(caps,0);
  const GstSegment *segment=gst_sample_get_segment(sample);
  /* Hardware encoders can shift PTS and segment together (e.g. by 1000 hours).
   * Restore pipeline running time before matching the source receipt metadata. */
  guint64 pts=segment?gst_segment_to_running_time(segment,GST_FORMAT_TIME,GST_BUFFER_PTS(b)):GST_BUFFER_PTS(b);
  gint w=0,h=0;gst_structure_get_int(s,"width",&w);gst_structure_get_int(s,"height",&h);
  g_mutex_lock(&settings_lock);guint bps=requested_bps;guint64 revision=applied_revision;g_mutex_unlock(&settings_lock);
  gboolean key=FALSE;
  if(gst_buffer_map(b,&map,GST_MAP_READ)){
    /* Subscribers require an IDR, not merely a non-delta/open-GOP I picture. */
    key=has_idr(map.data,map.size);
    char *json=g_strdup_printf("{\"type\":\"encoded\",\"pts_ns\":%"G_GUINT64_FORMAT",\"width\":%d,\"height\":%d,\"keyframe\":%s,\"configured_bitrate_bps\":%u,\"configuration_revision\":%"G_GUINT64_FORMAT"}",
       pts,w,h,key?"true":"false",bps,revision);
    emit(json,map.data,map.size);g_free(json);gst_buffer_unmap(b,&map);
  }
  g_mutex_lock(&preview_lock);GstElement *dest=preview_input?gst_object_ref(preview_input):NULL;g_mutex_unlock(&preview_lock);
  if(dest){
    guint64 queued=0;g_object_get(dest,"current-level-buffers",&queued,NULL);
    g_mutex_lock(&preview_lock);
    if(queued>=4)preview_needs_keyframe=TRUE;
    gboolean send=queued<4&&(!preview_needs_keyframe||key);
    if(send&&key)preview_needs_keyframe=FALSE;
    g_mutex_unlock(&preview_lock);
    if(send){GstBuffer *copy=gst_buffer_copy(b);GST_BUFFER_PTS(copy)=pts;GST_BUFFER_DTS(copy)=GST_CLOCK_TIME_NONE;
      gst_app_src_push_buffer(GST_APP_SRC(dest),copy);}
    gst_object_unref(dest);
  }
  gst_sample_unref(sample);return GST_FLOW_OK;
}
static gboolean preview_set(gpointer value) {
  gboolean enabled=GPOINTER_TO_INT(value);
  if(preview_pipeline&&!enabled){
    if(preview_bus_watch){g_source_remove(preview_bus_watch);preview_bus_watch=0;}
    g_mutex_lock(&preview_lock);preview_input=NULL;g_mutex_unlock(&preview_lock);
    gst_element_set_state(preview_pipeline,GST_STATE_NULL);gst_object_unref(preview_pipeline);preview_pipeline=NULL;
    message("preview_state","off");
  }else if(!preview_pipeline&&enabled){
    GError *error=NULL;
    const char *decoder=!strcmp(factory,"vtenc_h264_hw")?"vtdec_hw":"avdec_h264";
    char *desc=g_strdup_printf("appsrc name=decoded_source is-live=true format=time block=false max-buffers=4 caps=\"video/x-h264,stream-format=byte-stream,alignment=au\" ! h264parse ! %s ! videoconvert ! videoscale n-threads=1 ! videorate drop-only=true ! video/x-raw,format=I420,width=480,height=270,framerate=6/1 ! jpegenc quality=75 ! appsink name=decoded_sink emit-signals=true sync=false max-buffers=1 drop=true",decoder);
    preview_pipeline=gst_parse_launch(desc,&error);g_free(desc);
    if(error){message("preview_error",error->message);g_clear_error(&error);if(preview_pipeline)gst_object_unref(preview_pipeline);preview_pipeline=NULL;return G_SOURCE_REMOVE;}
    GstElement *sink=gst_bin_get_by_name(GST_BIN(preview_pipeline),"decoded_sink");
    g_signal_connect(sink,"new-sample",G_CALLBACK(on_preview),NULL);gst_object_unref(sink);
    GstElement *src=gst_bin_get_by_name(GST_BIN(preview_pipeline),"decoded_source");
    g_mutex_lock(&preview_lock);preview_input=src;preview_needs_keyframe=TRUE;g_mutex_unlock(&preview_lock);gst_object_unref(src);
    GstBus *bus=gst_element_get_bus(preview_pipeline);preview_bus_watch=gst_bus_add_watch(bus,on_preview_bus,NULL);gst_object_unref(bus);
    if(gst_element_set_state(preview_pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE){message("preview_error","Decoder pipeline failed to start");preview_set(GINT_TO_POINTER(0));}
    else {message("preview_state",decoder);force_keyframe();}
  }return G_SOURCE_REMOVE;
}
static gpointer input_thread(gpointer data) {
  gsize frame_bytes=GPOINTER_TO_SIZE(data);guint64 header[2];guint32 size;
  while(!g_atomic_int_get(&stopping)&&read_all(0,header,16)&&read_all(0,&size,4)){
    guint64 pts=GUINT64_FROM_BE(header[0]);size=GUINT32_FROM_BE(size);
    if(size!=frame_bytes){message("error","Invalid raw frame length");break;}
    GstBuffer *b=gst_buffer_new_allocate(NULL,size,NULL);GstMapInfo map;
    if(!gst_buffer_map(b,&map,GST_MAP_WRITE)){gst_buffer_unref(b);break;}
    gboolean ok=read_all(0,map.data,size);gst_buffer_unmap(b,&map);if(!ok){gst_buffer_unref(b);break;}
    GST_BUFFER_PTS(b)=pts;GST_BUFFER_DTS(b)=GST_CLOCK_TIME_NONE;GST_BUFFER_DURATION(b)=GST_SECOND/fps_out;
    if(gst_app_src_push_buffer(GST_APP_SRC(input),b)!=GST_FLOW_OK)break;
  }
  g_atomic_int_set(&stopping,1);g_main_loop_quit(loop);return NULL;
}
static gboolean apply_rate(gpointer line_ptr) {
  char *line=line_ptr;guint bps=0;guint64 revision=0;
  if(sscanf(line,"RATE %u %"G_GUINT64_FORMAT,&bps,&revision)==2&&bps>0){
    guint kbps=(bps+500)/1000;g_object_set(encoder,"bitrate",kbps,NULL);guint accepted=0;g_object_get(encoder,"bitrate",&accepted,NULL);
    g_mutex_lock(&settings_lock);requested_bps=accepted*1000;applied_revision=revision;g_mutex_unlock(&settings_lock);
    char *json=g_strdup_printf("{\"type\":\"configured\",\"bitrate_bps\":%u,\"configuration_revision\":%"G_GUINT64_FORMAT"}",accepted*1000,revision);emit(json,NULL,0);g_free(json);
  }else if(!strcmp(line,"KEYFRAME"))force_keyframe();
  g_free(line);return G_SOURCE_REMOVE;
}
static gpointer control_thread(gpointer fd_ptr) {
  FILE *f=fdopen(GPOINTER_TO_INT(fd_ptr),"r");if(!f)return NULL;char line[128];
  while(fgets(line,sizeof(line),f)){
    g_strchomp(line);
    if(!strcmp(line,"QUIT")){g_atomic_int_set(&stopping,1);g_main_loop_quit(loop);break;}
    if(!strcmp(line,"PREVIEW 1"))g_main_context_invoke(NULL,preview_set,GINT_TO_POINTER(1));
    else if(!strcmp(line,"PREVIEW 0"))g_main_context_invoke(NULL,preview_set,GINT_TO_POINTER(0));
    else g_main_context_invoke(NULL,apply_rate,g_strdup(line));
  }fclose(f);return NULL;
}
int main(int argc,char **argv) {
  signal(SIGPIPE,SIG_IGN);gst_init(NULL,NULL);loop=g_main_loop_new(NULL,FALSE);
  if(argc==2&&!strcmp(argv[1],"--probe")){
    const char *names[]={"vtenc_h264_hw","qsvh264enc","vtdec_hw","avdec_h264","appsrc","appsink","h264parse","videoscale","jpegenc",NULL};
    printf("{\"gstreamer_version\":\"%s\",\"factories\":{",gst_version_string());
    for(int i=0;names[i];i++){GstElementFactory *f=gst_element_factory_find(names[i]);printf("%s\"%s\":%s",i?",":"",names[i],f?"true":"false");if(f)gst_object_unref(f);}printf("}}\n");return 0;
  }
  if(argc!=10){fprintf(stderr,"factory source_w source_h output_w output_h fps bitrate control_fd revision\n");return 2;}
  factory=argv[1];guint sw=atoi(argv[2]),sh=atoi(argv[3]);width_out=atoi(argv[4]);height_out=atoi(argv[5]);fps_out=atoi(argv[6]);requested_bps=atoi(argv[7]);applied_revision=g_ascii_strtoull(argv[9],NULL,10);
  if((strcmp(factory,"vtenc_h264_hw")&&strcmp(factory,"qsvh264enc"))||!sw||!sh||!width_out||!height_out||!fps_out||fps_out>30||sw>3840||sh>2160||width_out>sw||height_out>sh||!requested_bps)return 2;
  char *enc_desc=!strcmp(factory,"vtenc_h264_hw")?g_strdup_printf("vtenc_h264_hw name=hardware bitrate=%u rate-control=cbr realtime=true allow-frame-reordering=false max-keyframe-interval=%u",(requested_bps+500)/1000,fps_out):g_strdup_printf("qsvh264enc name=hardware bitrate=%u rate-control=cbr b-frames=0 idr-interval=0 gop-size=%u",(requested_bps+500)/1000,fps_out);
  char *desc=g_strdup_printf("appsrc name=frames is-live=true format=time block=false max-buffers=2 leaky-type=downstream caps=\"video/x-raw,format=NV12,width=%u,height=%u,framerate=%u/1\" ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream ! videoscale n-threads=1 method=bilinear ! video/x-raw,format=NV12,width=%u,height=%u ! %s ! h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au ! appsink name=encoded emit-signals=true sync=false max-buffers=2 drop=false",sw,sh,fps_out,width_out,height_out,enc_desc);
  GError *error=NULL;pipeline=gst_parse_launch(desc,&error);g_free(desc);g_free(enc_desc);
  if(error){message("error",error->message);g_clear_error(&error);if(pipeline)gst_object_unref(pipeline);return 3;}
  input=gst_bin_get_by_name(GST_BIN(pipeline),"frames");encoder=gst_bin_get_by_name(GST_BIN(pipeline),"hardware");
  GstElement *sink=gst_bin_get_by_name(GST_BIN(pipeline),"encoded");g_signal_connect(sink,"new-sample",G_CALLBACK(on_encoded),NULL);gst_object_unref(sink);
  GstBus *bus=gst_element_get_bus(pipeline);gst_bus_add_watch(bus,on_bus,NULL);gst_object_unref(bus);
  if(gst_element_set_state(pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE){message("error","Hardware pipeline failed to start");return 4;}
  char *ready=g_strdup_printf("{\"type\":\"ready\",\"factory\":\"%s\",\"rate_control\":\"cbr\",\"gstreamer_version\":\"%s\"}",factory,gst_version_string());emit(ready,NULL,0);g_free(ready);
  GThread *raw_thread=g_thread_new("raw-input",input_thread,GSIZE_TO_POINTER((gsize)sw*sh*3/2));
  g_thread_unref(g_thread_new("control",control_thread,GINT_TO_POINTER(atoi(argv[8]))));
  g_main_loop_run(loop);g_atomic_int_set(&stopping,1);preview_set(GINT_TO_POINTER(0));gst_element_set_state(pipeline,GST_STATE_NULL);
  g_thread_join(raw_thread);
  gst_object_unref(input);gst_object_unref(encoder);gst_object_unref(pipeline);return 0;
}
