// hs_bench.c - TLS 1.3 handshake benchmark with in-memory BIO pairs (no network).
// Measures computation time of client and server separately (wall and thread-CPU),
// exact bytes per flight and optional record-layer cost after the handshake.
// Transmission time is NOT measured here: it is modeled afterwards (see notebook).
#define _GNU_SOURCE
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/bio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>

static double now_wall(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1e6+t.tv_nsec/1e3;}
static double now_cpu(void){struct timespec t;clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return t.tv_sec*1e6+t.tv_nsec/1e3;}
static void die(const char*m){fprintf(stderr,"ERROR: %s\n",m);ERR_print_errors_fp(stderr);exit(2);}


static long read_status_kb(const char*key){FILE*f=fopen("/proc/self/status","r");char line[256];long v=-1;size_t kl=strlen(key);
  if(!f)return -1;while(fgets(line,sizeof line,f)){if(!strncmp(line,key,kl)){v=atol(line+kl);break;}}fclose(f);return v;}

typedef struct { double cw,sw,cc,sc; size_t fb[8]; int nf; int ok; int reused; } res_t;

// one handshake over a fresh BIO pair; resume_sess may be NULL. Returns result; optionally returns client session.
static res_t do_hs(SSL_CTX*cctx,SSL_CTX*sctx,SSL_SESSION*resume_sess,SSL_SESSION**out_sess,SSL**keep_c,SSL**keep_s,BIO**keep_b1,BIO**keep_b2){
  res_t r;memset(&r,0,sizeof r);
  SSL*c=SSL_new(cctx),*s=SSL_new(sctx);BIO*b1,*b2;
  if(!BIO_new_bio_pair(&b1,1<<20,&b2,1<<20))die("bio pair");
  SSL_set_bio(c,b1,b1);SSL_set_bio(s,b2,b2);SSL_set_connect_state(c);SSL_set_accept_state(s);
  if(resume_sess)SSL_set_session(c,resume_sess);
  int cdone=0,sdone=0,guard=0,lastdir=-1;size_t pc=0,ps=0;
  while(!(cdone&&sdone)&&guard++<50){
    if(!cdone){
      double w0=now_wall(),c0=now_cpu();int x=SSL_do_handshake(c);double w1=now_wall(),c1=now_cpu();
      r.cw+=w1-w0;r.cc+=c1-c0;
      if(x==1)cdone=1;else{int e=SSL_get_error(c,x);if(e!=SSL_ERROR_WANT_READ&&e!=SSL_ERROR_WANT_WRITE)die("client handshake");}
      size_t tot=BIO_number_written(b1);size_t d=tot-pc;pc=tot;
      if(d>0){if(lastdir!=0){if(r.nf<8)r.nf++;lastdir=0;}r.fb[r.nf-1]+=d;}
    }
    if(!sdone){
      double w0=now_wall(),c0=now_cpu();int x=SSL_do_handshake(s);double w1=now_wall(),c1=now_cpu();
      r.sw+=w1-w0;r.sc+=c1-c0;
      if(x==1)sdone=1;else{int e=SSL_get_error(s,x);if(e!=SSL_ERROR_WANT_READ&&e!=SSL_ERROR_WANT_WRITE)die("server handshake");}
      size_t tot=BIO_number_written(b2);size_t d=tot-ps;ps=tot;
      if(d>0){if(lastdir!=1){if(r.nf<8)r.nf++;lastdir=1;}r.fb[r.nf-1]+=d;}
    }
  }
  r.ok=(cdone&&sdone);r.reused=SSL_session_reused(c);
  if(!r.ok)die("handshake did not finish");
  if(out_sess){ char b[16]; SSL_read(c,b,1); *out_sess=SSL_get1_session(c); }  // processes NewSessionTicket
  if(keep_c){*keep_c=c;*keep_s=s;*keep_b1=b1;*keep_b2=b2;}else{SSL_set_shutdown(c,SSL_SENT_SHUTDOWN|SSL_RECEIVED_SHUTDOWN);SSL_set_shutdown(s,SSL_SENT_SHUTDOWN|SSL_RECEIVED_SHUTDOWN);SSL_free(c);SSL_free(s);}
  return r;
}

int main(int argc,char**argv){
  const char *cert=NULL,*key=NULL,*ca=NULL,*groups="X25519",*sigalgs=NULL,*mode="full";
  int n=100,warm=10,msgs=0,msgsize=64;
  for(int i=1;i<argc;i++){
    if(!strcmp(argv[i],"--cert"))cert=argv[++i];
    else if(!strcmp(argv[i],"--key"))key=argv[++i];
    else if(!strcmp(argv[i],"--ca"))ca=argv[++i];
    else if(!strcmp(argv[i],"--groups"))groups=argv[++i];
    else if(!strcmp(argv[i],"--sigalgs"))sigalgs=argv[++i];
    else if(!strcmp(argv[i],"--mode"))mode=argv[++i];        // full | resume
    else if(!strcmp(argv[i],"--msgs"))msgs=atoi(argv[++i]);  // application messages after handshake
    else if(!strcmp(argv[i],"--msgsize"))msgsize=atoi(argv[++i]);
    else if(!strcmp(argv[i],"-n"))n=atoi(argv[++i]);
    else if(!strcmp(argv[i],"--warmup"))warm=atoi(argv[++i]);
  }
  if(!cert||!key||!ca){fprintf(stderr,"usage: --cert --key --ca [--groups g] [--sigalgs s] [--mode full|resume] [--msgs K --msgsize M] [-n N] [--warmup W]\n");return 1;}
  int resume=!strcmp(mode,"resume");
  SSL_CTX*sctx=SSL_CTX_new(TLS_server_method()),*cctx=SSL_CTX_new(TLS_client_method());
  if(!sctx||!cctx)die("ctx");
  SSL_CTX_set_min_proto_version(sctx,TLS1_3_VERSION);SSL_CTX_set_max_proto_version(sctx,TLS1_3_VERSION);
  SSL_CTX_set_min_proto_version(cctx,TLS1_3_VERSION);SSL_CTX_set_max_proto_version(cctx,TLS1_3_VERSION);
  if(resume){SSL_CTX_set_num_tickets(sctx,1);SSL_CTX_set_session_cache_mode(cctx,SSL_SESS_CACHE_CLIENT);}
  else{SSL_CTX_set_options(sctx,SSL_OP_NO_TICKET);SSL_CTX_set_num_tickets(sctx,0);}
  SSL_CTX_set_session_cache_mode(sctx,SSL_SESS_CACHE_OFF);SSL_CTX_set_session_id_context(sctx,(const unsigned char*)"pq",2);
  if(SSL_CTX_use_certificate_chain_file(sctx,cert)!=1)die("cert");
  if(SSL_CTX_use_PrivateKey_file(sctx,key,SSL_FILETYPE_PEM)!=1)die("key");
  if(SSL_CTX_load_verify_locations(cctx,ca,NULL)!=1)die("ca");
  SSL_CTX_set_verify(cctx,SSL_VERIFY_PEER,NULL);
  if(SSL_CTX_set1_groups_list(sctx,groups)!=1)die("server groups");
  if(SSL_CTX_set1_groups_list(cctx,groups)!=1)die("client groups");
  if(sigalgs){ if(SSL_CTX_set1_sigalgs_list(sctx,sigalgs)!=1)die("server sigalgs"); if(SSL_CTX_set1_sigalgs_list(cctx,sigalgs)!=1)die("client sigalgs"); }
  SSL_SESSION*sess=NULL;
  long rss_base=read_status_kb("VmRSS:");
  printf("iter,client_us,server_us,client_cpu_us,server_cpu_us,flights,f1_bytes,f2_bytes,f3_bytes,f4_bytes,c2s_bytes,s2c_bytes,app_c_us,app_s_us,app_overhead_bytes,resumed\n");
  for(int it=-warm;it<n;it++){
    SSL*c=NULL,*s=NULL;BIO*b1=NULL,*b2=NULL;
    if(resume){ // tickets are single-use: obtain a fresh one with an UNTIMED full handshake
      if(sess){SSL_SESSION_free(sess);sess=NULL;}
      do_hs(cctx,sctx,NULL,&sess,NULL,NULL,NULL,NULL); if(!sess)die("no session ticket obtained");
    }
    res_t r=do_hs(cctx,sctx,resume?sess:NULL,NULL,msgs?&c:NULL,msgs?&s:NULL,msgs?&b1:NULL,msgs?&b2:NULL);
    double ac=0,as=0,ovh=0;
    if(msgs){
      char*buf=malloc(msgsize),*rb=malloc(msgsize);memset(buf,0x5a,msgsize);
      size_t w0=BIO_number_written(b1);
      for(int k=0;k<msgs;k++){
        double a=now_cpu();if(SSL_write(c,buf,msgsize)!=msgsize)die("app write");ac+=now_cpu()-a;
        a=now_cpu();if(SSL_read(s,rb,msgsize)!=msgsize)die("app read");as+=now_cpu()-a;
      }
      ovh=((double)(BIO_number_written(b1)-w0))/msgs-msgsize;
      ac/=msgs;as/=msgs;free(buf);free(rb);SSL_set_shutdown(c,SSL_SENT_SHUTDOWN|SSL_RECEIVED_SHUTDOWN);SSL_set_shutdown(s,SSL_SENT_SHUTDOWN|SSL_RECEIVED_SHUTDOWN);SSL_free(c);SSL_free(s);
    }
    size_t c2s=0,s2c=0;
    // direction-resolved totals: flights alternate c,s,c,...
    for(int i=0;i<r.nf;i++){ if(i%2==0)c2s+=r.fb[i]; else s2c+=r.fb[i]; }
    if(it>=0)printf("%d,%.1f,%.1f,%.1f,%.1f,%d,%zu,%zu,%zu,%zu,%zu,%zu,%.2f,%.2f,%.1f,%d\n",it,r.cw,r.sw,r.cc,r.sc,r.nf,r.fb[0],r.fb[1],r.fb[2],r.fb[3],c2s,s2c,ac,as,ovh,r.reused);
  }
  fprintf(stderr,"peak_rss_kb=%ld rss_base_kb=%ld\n",read_status_kb("VmHWM:"),rss_base);
  return 0;
}