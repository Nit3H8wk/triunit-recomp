#include "launcher_backend.hpp"
#include "mk2_profile.hpp"
#include "mk2_program.hpp"
#include "mk5_operator_settings.hpp"
#include "mk5_program.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
namespace fs=std::filesystem;
namespace {
bool same(const mklauncher::GameAdjustments& a,const mklauncher::GameAdjustments& b){return a.difficulty==b.difficulty&&a.coinage==b.coinage&&a.freePlay==b.freePlay&&a.customCoinage==b.customCoinage;}
std::vector<uint8_t> lane(const fs::path& path){
 for(auto p=fs::absolute(path);!p.empty();){const auto attr=GetFileAttributesW(p.c_str());if(attr!=INVALID_FILE_ATTRIBUTES&&(attr&FILE_ATTRIBUTE_REPARSE_POINT))throw std::runtime_error("linked operator ROM path");const auto parent=p.parent_path();if(parent==p)break;p=parent;}
 if(fs::file_size(path)!=0x80000)throw std::runtime_error("operator ROM size differs");
 std::ifstream file(path,std::ios::binary);std::vector<uint8_t> data(0x80000);
 if(!file.read(reinterpret_cast<char*>(data.data()),data.size())||file.peek()!=EOF)throw std::runtime_error("operator ROM read failed");
 return data;
}
}
namespace mklauncher {
bool Backend::adjustmentsAvailable()const{return adjustmentsAvailable_;}
bool Backend::dipSwitchesAvailable()const{return adjustmentsAvailable_||gameIndex_==2;}
bool Backend::refreshAdjustments(bool read){
 adjustmentsAvailable_=false;adjustments={};adjustmentsImage_.clear();adjustmentsProgram_.clear();coinageLabels_.clear();adjustmentsSha_.clear();
 if(!read)return false;
 try{
  adjustmentsPath_=operatorPath(false);if(adjustmentsPath_.empty()||!fs::exists(adjustmentsPath_))return false;
  auto profile=mk2::LoadCmosFile(adjustmentsPath_);
  if(!mkoperator::SettingsChecksumValid(profile.image))throw std::runtime_error("operator settings checksum differs");
  GameAdjustments current;current.difficulty=int(mkoperator::ReadParameter(profile.image,14));current.coinage=int(mkoperator::ReadParameter(profile.image,1));
  const auto freeplay=mkoperator::ReadParameter(profile.image,18);current.freePlay=freeplay!=0;current.customCoinage=mkoperator::ReadParameter(profile.image,21)==0;
  if(current.difficulty<1||current.difficulty>5||current.coinage<1||current.coinage>58||freeplay>1)throw std::runtime_error("native operator value outside ROM menu range");
  const auto roms=operatorRoms();
  auto program=gameIndex_==0?LoadMk5Program(roms).bytes:mk2::VerifyProgramLanes(lane(roms/L"uj12.l31"),lane(roms/L"ug12.l31")).bytes;
  const auto game=gameIndex_==0?mkoperator::Game::Mk1:mkoperator::Game::Mk2;
  for(unsigned n=1;n<=58;++n){
   const auto text=mkoperator::CoinageLabel(game,program,n);std::wstring label(text.begin(),text.end());
   const auto at=mkoperator::CoinageOffset(game,n);label+=L" / "+std::to_wstring(mkoperator::ProgramField(program,at+14,2))+L" / "+std::to_wstring(mkoperator::ProgramField(program,at+16,2));
   coinageLabels_.push_back(std::move(label));
  }
  adjustments=current;adjustmentsImage_=std::move(profile.image);adjustmentsSha_=std::move(profile.sha256);adjustmentsProgram_=std::move(program);adjustmentsAvailable_=true;return true;
 }catch(...){status_=L"Game adjustments unavailable: check the profile's CMOS and ROM files.";return false;}
}
std::wstring Backend::coinageLabel(const GameAdjustments& value)const{
 if(value.freePlay)return L"FREE PLAY";
 if(value.customCoinage)return L"CUSTOM / CMOS";
 if(value.coinage>=1&&size_t(value.coinage)<=coinageLabels_.size())return coinageLabels_[size_t(value.coinage-1)];
 return L"PRESET "+std::to_wstring(value.coinage);
}
bool Backend::saveAll(const Config& requested,const GameAdjustments& wanted){
 if(running()){status_=L"Close the game before saving adjustments.";return false;}
 if(wanted.difficulty<1||wanted.difficulty>5||wanted.coinage<1||wanted.coinage>58){status_=L"Adjustments outside the arcade's values.";return false;}
 const auto before=config;const bool changed=!same(wanted,adjustments);auto image=adjustmentsImage_;
 try{
  if(operatorPath()!=adjustmentsPath_)throw std::runtime_error("selected operator profile changed; reopen Settings");
  if(changed&&!adjustmentsAvailable_)throw std::runtime_error("operator profile unavailable");
  const bool repricing=wanted.coinage!=adjustments.coinage||(!wanted.customCoinage&&adjustments.customCoinage);
  if(changed){
   if(repricing)mkoperator::ApplyCoinage(image,adjustmentsProgram_,gameIndex_==0?mkoperator::Game::Mk1:mkoperator::Game::Mk2,unsigned(wanted.coinage),wanted.freePlay);
   else mkoperator::WriteParameter(image,18,wanted.freePlay?1:0);
   mkoperator::WriteParameter(image,14,uint32_t(wanted.difficulty));mkoperator::UpdateSettingsChecksum(image);
  }
  auto commit=[&]{
   config=requested;
   if(repricing||wanted.freePlay!=adjustments.freePlay)config.cmosCoinage=true;
   if(!save())throw std::runtime_error("preferences atomic save failed");
  };
  if(adjustmentsAvailable_){
   const auto sha=mk2::CompareAndSwapCmosFile(adjustmentsPath_,image,adjustmentsSha_,gameIndex_==0?mk2::CmosLock::Mk1Session:mk2::CmosLock::Mk2Profile,commit);
   adjustments=wanted;adjustmentsImage_=std::move(image);adjustmentsSha_=sha;
  }else commit();
  status_=L"Preferences and adjustments saved for this game.";return true;
 }catch(const std::exception& error){
  std::clog<<"operator save failed: "<<error.what()<<'\n';
  config=before;status_=L"Could not save; check access and whether the profile changed, then reopen the adjustments.";return false;
 }
}

bool Backend::resetHighScores(){
 if(running()||!adjustmentsAvailable_){status_=L"Ranking unavailable: close the game and open the adjustments.";return false;}
 try{
  if(operatorPath()!=adjustmentsPath_)throw std::runtime_error("selected ranking profile changed; reopen Settings");
  auto image=adjustmentsImage_;mkoperator::ResetHighScores(image,adjustmentsProgram_,gameIndex_==0?mkoperator::Game::Mk1:mkoperator::Game::Mk2);
  adjustmentsSha_=mk2::CompareAndSwapCmosFile(adjustmentsPath_,image,adjustmentsSha_,gameIndex_==0?mk2::CmosLock::Mk1Session:mk2::CmosLock::Mk2Profile);
  adjustmentsImage_=std::move(image);status_=L"Ranking reset by the arcade's own routine.";return true;
 }catch(...){status_=L"Could not reset the ranking; the profile was not replaced.";return false;}
}
}
