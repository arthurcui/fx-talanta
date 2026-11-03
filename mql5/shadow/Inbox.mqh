#ifndef FX_SHADOW_INBOX
#define FX_SHADOW_INBOX
#include "Protocol.mqh"
#include "../gateway/Core.mqh"
class ShInbox
{
private:
   FxJournal journal;
   string scope,release,policy,binding;
   string works[],receipts[];
   int acknowledged;
public:
   ShInbox(){ acknowledged=0; }
   void Close(){ journal.Close(); }
   string Pending(){ return acknowledged<ArraySize(receipts) ? receipts[acknowledged] : ""; }
   bool Open(string path,string account_scope,string client,string pinned_release,string pinned_policy,string key,bool bootstrap)
   {
      scope=account_scope; release=pinned_release; policy=pinned_policy;
      binding="BIND\t"+scope+"\t"+client+"\t"+release+"\t"+policy+"\t"+FxHash(ShHex(key));
      bool exists=FileIsExist(path);
      if(exists==bootstrap) return false;
      string rows[];
      if(!journal.Open(path,rows)) return false;
      ArrayResize(works,0); ArrayResize(receipts,0); acknowledged=0;
      if(bootstrap && ArraySize(rows)==0) return journal.Append(binding);
      if(ArraySize(rows)<1 || rows[0]!=binding) { Close(); return false; }
      for(int i=1;i<ArraySize(rows);i++)
      {
         string f[],work,receipt;
         if(StringSplit(rows[i],'\t',f)==3 && f[0]=="RECEIPT")
         {
            if(Pending()!="" || !ShUnhex(f[1],work) || !ShUnhex(f[2],receipt)) { Close(); return false; }
            string r[]; if(StringSplit(receipt,'\t',r)!=10 || r[9]!="0" || !FxInteger(r[5]) || !FxInteger(r[8]) ||
               ShAssess(work,scope,release,policy,StringToInteger(r[5]),(int)StringToInteger(r[8]))!=receipt ||
               StringToInteger(r[3])!=ArraySize(receipts)+1) { Close(); return false; }
            int n=ArraySize(receipts); ArrayResize(receipts,n+1); ArrayResize(works,n+1);
            receipts[n]=receipt; works[n]=work;
         }
         else if(ArraySize(f)==2 && f[0]=="ACK" && Pending()!="" && f[1]==FxHash(Pending())) acknowledged++;
         else { Close(); return false; }
      }
      return true;
   }
   bool Receive(string work,long now,int error)
   {
      if(Pending()!="") return false;
      string f[],v[];
      if(!ShWork(work,scope,release,policy,f,v) || StringToInteger(f[6])!=ArraySize(receipts)+1) return false;
      for(int i=0;i<ArraySize(works);i++)
      { string prior[]; StringSplit(works[i],'\t',prior); if(prior[1]==f[1]) return false; }
      string receipt=ShAssess(work,scope,release,policy,now,error);
      if(receipt=="" || !journal.Append("RECEIPT\t"+ShHex(work)+"\t"+ShHex(receipt))) return false;
      int n=ArraySize(receipts); ArrayResize(receipts,n+1); ArrayResize(works,n+1);
      receipts[n]=receipt; works[n]=work; return true;
   }
   bool Ack(string hash)
   {
      if(Pending()=="" || FxHash(Pending())!=hash || !journal.Append("ACK\t"+hash)) return false;
      acknowledged++; return true;
   }
};
#endif
