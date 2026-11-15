// sig_bench.c - sign/verify benchmark for firmware signature schemes (EVP).
#define _GNU_SOURCE
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/err.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>
static double now_cpu(void){struct timespec t;clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return t.tv_sec*1e6+t.tv_nsec/1e3;}

static long read_status_kb(const char*key){FILE*f=fopen("/proc/self/status","r");char line[256];long v=-1;size_t kl=strlen(key);
  if(!f)return -1;while(fgets(line,sizeof line,f)){if(!strncmp(line,key,kl)){v=atol(line+kl);break;}}fclose(f);return v;}
static void die(const char*m){fprintf(stderr,"ERROR: %s\n",m);ERR_print_errors_fp(stderr);exit(2);}
int main(int argc,char**argv){
  const char*key=NULL,*md=NULL;size_t size=1<<20;int n=100,warm=5;
  for(int i=1;i<argc;i++){
    if(!strcmp(argv[i],"--key"))key=argv[++i];
    else if(!strcmp(argv[i],"--md"))md=argv[++i];   // omit for pure (ML-DSA, SLH-DSA)
    else if(!strcmp(argv[i],"--size"))size=strtoull(argv[++i],0,10);
    else if(!strcmp(argv[i],"-n"))n=atoi(argv[++i]);
    else if(!strcmp(argv[i],"--warmup"))warm=atoi(argv[++i]);
  }
  if(!key){fprintf(stderr,"usage: --key priv.pem [--md sha256] [--size bytes] [-n N]\n");return 1;}
  long rss_base=read_status_kb("VmRSS:");
  BIO*bf=BIO_new_file(key,"r");if(!bf)die("open key");
  EVP_PKEY*pk=PEM_read_bio_PrivateKey(bf,NULL,NULL,NULL);if(!pk)die("read key");
  unsigned char*msg=malloc(size);RAND_bytes(msg,(int)size);
  const EVP_MD*mdp=md?EVP_get_digestbyname(md):NULL;
  EVP_MD_CTX*ctx=EVP_MD_CTX_new();size_t siglen=0;
  if(EVP_DigestSignInit(ctx,NULL,mdp,NULL,pk)!=1)die("signinit");
  if(EVP_DigestSign(ctx,NULL,&siglen,msg,size)!=1)die("siglen");
  unsigned char*sig=malloc(siglen);
  double t0=now_cpu();
  if(EVP_DigestSign(ctx,sig,&siglen,msg,size)!=1)die("sign");
  double sign_us=now_cpu()-t0;EVP_MD_CTX_free(ctx);
  printf("# sig_bytes=%zu sign_us=%.1f msg_bytes=%zu\niter,verify_us\n",siglen,sign_us,size);
  for(int it=-warm;it<n;it++){
    EVP_MD_CTX*v=EVP_MD_CTX_new();double a=now_cpu();
    if(EVP_DigestVerifyInit(v,NULL,mdp,NULL,pk)!=1)die("verifyinit");
    int r=EVP_DigestVerify(v,sig,siglen,msg,size);double b=now_cpu();
    if(r!=1)die("verify failed");
    if(it>=0)printf("%d,%.1f\n",it,b-a);
    EVP_MD_CTX_free(v);
  }
  fprintf(stderr,"peak_rss_kb=%ld rss_base_kb=%ld\n",read_status_kb("VmHWM:"),rss_base);
  return 0;
}