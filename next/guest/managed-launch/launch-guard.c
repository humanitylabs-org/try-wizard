/* External packaging admission, not a Hermes patch. Linux only.
 * All shipped Python executable inodes are replaced by this launcher. The
 * original interpreter is root-only; setuid is used ONLY to open that inode,
 * then privileges are dropped before admission and fexecve. argv[0] remains
 * the public Python path so sys.executable and child launches use the guard.
 */
#define _GNU_SOURCE
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
extern char **environ;
#define ROOT "/wizard-managed-state"
#ifndef REAL_PATH
#define REAL_PATH "/opt/wizard-managed/private/python"
#endif
static void fail(const char *s) { fprintf(stderr,"Wizard maintenance: %s\n",s); exit(75); }
static long parent(long pid) {
 char p[128],b[4096]; snprintf(p,sizeof p,"/proc/%ld/stat",pid);
 FILE *f=fopen(p,"r"); if(!f)return 0;
 if(!fgets(b,sizeof b,f)){fclose(f);return 0;} fclose(f);
 char *end=strrchr(b,')'); long pp=0; char state;
 if(end)sscanf(end+1," %c %ld",&state,&pp);
 return pp;
}
static unsigned long long started(long pid) {
 char path[128],buf[4096];snprintf(path,sizeof path,"/proc/%ld/stat",pid);
 FILE *f=fopen(path,"r");if(!f)return 0;
 if(!fgets(buf,sizeof buf,f)){fclose(f);return 0;}fclose(f);
 char *end=strrchr(buf,')'),*save=NULL;if(!end)return 0;
 char *field=strtok_r(end+2," ",&save);
 for(int n=0;field&&n<19;n++)field=strtok_r(NULL," ",&save);
 return field?strtoull(field,NULL,10):0;
}
static int descendant(const char *host) {
 long p=getppid();
 for(int i=0;p>1&&i<128;i++,p=parent(p)) {
  char path[512];snprintf(path,sizeof path,ROOT "/launch/%s-%ld",host,p);
  int fd=open(path,O_RDONLY|O_NOFOLLOW);
  if(fd<0)continue;
  int held=flock(fd,LOCK_EX|LOCK_NB)<0&&(errno==EAGAIN||errno==EWOULDBLOCK);
  char record[128]={0};long owner=0;unsigned long long epoch=0;
  if(read(fd,record,sizeof(record)-1)>0)sscanf(record,"%ld %llu",&owner,&epoch);
  held=held&&owner==p&&epoch!=0&&epoch==started(p);
  close(fd);if(held)return 1;
 }
 return 0;
}
int main(int argc,char **argv) {
 (void)argc;
 int executable=open(REAL_PATH,O_RDONLY|O_CLOEXEC);
 if(executable<0)fail("interpreter unavailable");
 uid_t uid=getuid();gid_t gid=getgid();
 if(setresgid(gid,gid,gid)||setresuid(uid,uid,uid))fail("cannot drop privileges");
 char host[128];if(gethostname(host,sizeof host)||strchr(host,'/'))fail("runtime identity unknown");
 int mutex=open(ROOT "/admission.lock",O_RDWR|O_CLOEXEC|O_NOFOLLOW);
 if(mutex<0||flock(mutex,LOCK_EX))fail("supervisor unavailable; launch refused");
 struct stat st;
 if(lstat(ROOT "/lease.json",&st)==0&&!descendant(host))fail("update holds launch admission; retry after update or cancel");
 if(errno!=ENOENT&&lstat(ROOT "/lease.json",&st)<0)fail("lease state unknown");
 char path[512];snprintf(path,sizeof path,ROOT "/launch/%s-%ld",host,(long)getpid());
 int reserve=open(path,O_RDWR|O_CREAT|O_TRUNC|O_NOFOLLOW,0600);
 if(reserve<0||flock(reserve,LOCK_EX|LOCK_NB))fail("cannot reserve process lifetime");
 dprintf(reserve,"%ld %llu\n",(long)getpid(),started(getpid()));
 /* Deliberately inherited across exec/fork: ownership is actual process lifetime,
    never an idle sample or an environment-variable assertion. */
 if(fcntl(reserve,F_SETFD,0))fail("cannot retain reservation");
 flock(mutex,LOCK_UN);close(mutex);
 fexecve(executable,argv,environ);fail("interpreter exec failed");
}
