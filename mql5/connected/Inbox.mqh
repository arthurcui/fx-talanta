#ifndef FX_CONNECTED_INBOX
#define FX_CONNECTED_INBOX
#include "Protocol.mqh"
// Exclusive binary journal retains its exact bytes, including CRLF, for the
// checkpoint SHA. No gateway, sender or broker mutation is instantiated here.
class CoInbox
{
private:
   int handle,acked;
   long journal_sequence;
   string journal_text,previous,scope,incarnation,epoch,binding_hash,binding,checkpoint;
   string observations[],receipts[];
   bool Append(string record)
   {
      if(handle==INVALID_HANDLE || journal_sequence>=4096 || StringFind(record,"|")>=0 || StringLen(record)>8000 ||
         FileSize(handle)!=(ulong)StringLen(journal_text) || StringLen(journal_text)>8000000) return false;
      string body=IntegerToString(journal_sequence+1)+"|"+previous+"|"+record;
      string hash=FxHash(body),line=body+"|"+hash+"\r\n";
      uchar bytes[]; int count=StringToCharArray(line,bytes,0,WHOLE_ARRAY,CP_UTF8)-1;
      ArrayResize(bytes,count); ResetLastError();
      if(!FileSeek(handle,0,SEEK_END) || (int)FileWriteArray(handle,bytes)!=count) return false;
      FileFlush(handle); if(GetLastError()!=0) return false;
      journal_text+=line; previous=hash; journal_sequence++; return true;
   }
   string CheckpointText()
   {
      int total=ArraySize(receipts);
      return "connected-checkpoint/1\t"+scope+"\t"+incarnation+"\t"+epoch+"\t"+FxHash(journal_text)+"\t"+
         IntegerToString(total)+"\t"+(total==0 ? StringFormat("%064d",0) : FxHash(receipts[total-1]))+"\t"+
         (total==acked ? "1" : "0")+"\r\n";
   }
   bool SaveCheckpoint()
   {
      string temp=checkpoint+".pending";
      if(FileIsExist(temp)) return false;
      int file=FileOpen(temp,FILE_WRITE|FILE_BIN);
      if(file==INVALID_HANDLE) return false;
      uchar bytes[]; string text=CheckpointText();
      int n=StringToCharArray(text,bytes,0,WHOLE_ARRAY,CP_UTF8)-1; ArrayResize(bytes,n);
      ResetLastError(); bool ok=(int)FileWriteArray(file,bytes)==n;
      FileFlush(file); ok=ok && GetLastError()==0; FileClose(file);
      return ok && FileMove(temp,0,checkpoint,FILE_REWRITE);
   }
   bool ReadExact(string path,string &text)
   {
      text=""; int file=FileOpen(path,FILE_READ|FILE_BIN);
      if(file==INVALID_HANDLE) return false;
      ulong size=FileSize(file); if(size>8192){ FileClose(file); return false; }
      uchar bytes[]; ArrayResize(bytes,(int)size);
      bool ok=(ulong)FileReadArray(file,bytes)==size; FileClose(file);
      if(ok) text=CharArrayToString(bytes,0,(int)size,CP_UTF8);
      return ok;
   }
public:
   CoInbox(){ handle=INVALID_HANDLE; acked=0; journal_sequence=0; previous="GENESIS"; }
   void Close(){ if(handle!=INVALID_HANDLE) FileClose(handle); handle=INVALID_HANDLE; }
   string Pending(){ return acked<ArraySize(receipts) ? receipts[acked] : ""; }
   bool Open(string path,string checkpoint_path,string account_scope,string client,string inc,string writer_epoch,string pinned_binding,string key,bool bootstrap)
   {
      Close(); scope=account_scope; incarnation=inc; epoch=writer_epoch; binding_hash=pinned_binding; checkpoint=checkpoint_path;
      binding="BIND\t"+scope+"\t"+client+"\t"+incarnation+"\t"+epoch+"\t"+binding_hash+"\t"+FxHash(ShHex(key));
      bool exists=FileIsExist(path);
      if(exists==bootstrap || (bootstrap && FileIsExist(checkpoint)) || FileIsExist(checkpoint+".pending")) return false;
      string saved_checkpoint;
      if(!bootstrap && !ReadExact(checkpoint,saved_checkpoint)) return false;
      handle=FileOpen(path,FILE_READ|FILE_WRITE|FILE_BIN);
      if(handle==INVALID_HANDLE) return false;
      ulong size=FileSize(handle);
      if(size>8000000){ Close(); return false; }
      uchar bytes[]; ArrayResize(bytes,(int)size);
      if((ulong)FileReadArray(handle,bytes)!=size){ Close(); return false; }
      journal_text=CharArrayToString(bytes,0,(int)size,CP_UTF8);
      if(StringLen(journal_text)!=(int)size){ Close(); return false; }
      ArrayResize(observations,0); ArrayResize(receipts,0); acked=0; journal_sequence=0; previous="GENESIS";
      int cursor=0;
      while(cursor<StringLen(journal_text))
      {
         int ending=StringFind(journal_text,"\r\n",cursor); string row[];
         if(ending<cursor){ Close(); return false; }
         string line=StringSubstr(journal_text,cursor,ending-cursor); cursor=ending+2;
         if(StringLen(line)>8192 || StringSplit(line,'|',row)!=4 || !FxInteger(row[0]) ||
            StringToInteger(row[0])!=journal_sequence+1 || row[1]!=previous || FxHash(row[0]+"|"+row[1]+"|"+row[2])!=row[3])
         { Close(); return false; }
         if(journal_sequence==0){ if(row[2]!=binding){ Close(); return false; } }
         else
         {
            string f[],obs,receipt,fields[]; int count=StringSplit(row[2],'\t',f);
            if(count==3 && f[0]=="RECEIPT")
            {
               if(Pending()!="" || !ShUnhex(f[1],obs) || !ShUnhex(f[2],receipt) ||
                  !CoReceiptValid(obs,receipt,scope,binding_hash) || !CoObservation(obs,scope,binding_hash,fields) ||
                  StringToInteger(fields[2])!=ArraySize(receipts)+1){ Close(); return false; }
               for(int n=0;n<ArraySize(observations);n++)
               { string old[]; StringSplit(observations[n],'\t',old); if(old[1]==fields[1]){ Close(); return false; } }
               int n=ArraySize(receipts); ArrayResize(receipts,n+1); ArrayResize(observations,n+1);
               observations[n]=obs; receipts[n]=receipt;
            }
            else if(count==2 && f[0]=="ACK" && Pending()!="" && FxHash(Pending())==f[1]) acked++;
            else { Close(); return false; }
         }
         previous=row[3]; journal_sequence++;
         if(journal_sequence>4096){ Close(); return false; }
      }
      if(bootstrap)
      {
         if(journal_sequence!=0 || !Append(binding) || !SaveCheckpoint()){ Close(); return false; }
      }
      else if(journal_sequence<1 || saved_checkpoint!=CheckpointText()){ Close(); return false; }
      return true;
   }
   bool Receive(string obs,string receipt)
   {
      string fields[];
      if(Pending()!="" || ArraySize(receipts)>=1024 || !CoObservation(obs,scope,binding_hash,fields) ||
         StringToInteger(fields[2])!=ArraySize(receipts)+1 || !CoReceiptValid(obs,receipt,scope,binding_hash)) return false;
      for(int n=0;n<ArraySize(observations);n++)
      { string old[]; StringSplit(observations[n],'\t',old); if(old[1]==fields[1]) return false; }
      if(!Append("RECEIPT\t"+ShHex(obs)+"\t"+ShHex(receipt))) return false;
      int n=ArraySize(receipts); ArrayResize(receipts,n+1); ArrayResize(observations,n+1);
      receipts[n]=receipt; observations[n]=obs;
      if(!SaveCheckpoint()){ Close(); return false; }
      return true;
   }
   bool Ack(string hash)
   {
      if(Pending()=="" || !FxHex(hash,64) || FxHash(Pending())!=hash || !Append("ACK\t"+hash)) return false;
      acked++; if(!SaveCheckpoint()){ Close(); return false; } return true;
   }
};
#endif
