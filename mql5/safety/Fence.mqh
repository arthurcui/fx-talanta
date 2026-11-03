#ifndef FX_SAFETY_FENCE
#define FX_SAFETY_FENCE
// HMAC-SHA256, fixed private per-account key, explicit domain separation.
// HTTPS and pinned identity are additional deployment gates, not replaced by this.
string SHmac(string key,string text)
{
   uchar secret[],message[],empty[],inner[],outer[],first[],last[];
   int length=StringToCharArray(key,secret,0,WHOLE_ARRAY,CP_UTF8)-1;
   if(length<32 || length>64) return "";
   int size=StringToCharArray(text,message,0,WHOLE_ARRAY,CP_UTF8)-1;
   ArrayResize(inner,64+size); ArrayResize(outer,96);
   for(int i=0;i<64;i++)
   { uchar v=(i<length ? secret[i] : 0); inner[i]=v^0x36; outer[i]=v^0x5c; }
   for(int i=0;i<size;i++) inner[64+i]=message[i];
   if(CryptEncode(CRYPT_HASH_SHA256,inner,empty,first)!=32) return "";
   for(int i=0;i<32;i++) outer[64+i]=first[i];
   if(CryptEncode(CRYPT_HASH_SHA256,outer,empty,last)!=32) return "";
   string result=""; for(int i=0;i<32;i++) result+=StringFormat("%02x",last[i]);
   return result;
}
string SFence(long pinned_epoch,long epoch,long expires,long now,int clock_error,long last_sequence,long sequence,bool reconciled,bool storage,bool authenticated)
{
   if(!storage) return "STORAGE_UNAVAILABLE";
   if(!authenticated) return "AUTHENTICATION_FAILURE";
   if(!reconciled) return "STARTUP_RECONCILE";
   if(clock_error<0 || clock_error>100) return "CLOCK_UNVERIFIED";
   if(pinned_epoch!=epoch) return "FENCED";
   if(now+clock_error>=expires) return "EXPIRED";
   if(sequence!=last_sequence+1) return "SEQUENCE_CONFLICT";
   return "ACCEPTED";
}
#endif
