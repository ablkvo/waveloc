#!/usr/bin/env python
# encoding: utf-8

import os, sys, optparse, glob
from obspy.core import *
import matplotlib.pyplot as plt
import numpy as np
from OP_waveforms import *
from obspy.signal.cross_correlation import *
import time, cProfile
import cPickle
import logging
from locations_trigger import read_locs_from_file

class BinaryFile(object):
  def __init__(self,filename):
    self.filename=filename
  def read_binary_file(self):
    with open(self.filename,'rb') as test:
      my_depickler=cPickle.Unpickler(test)
      result=my_depickler.load()
      test.close()
    return result
  def write_binary_file(self,input):
    with open(self.filename,'wb') as test:
      my_pickler=cPickle.Pickler(test)
      my_pickler.dump(input)
      test.close()

def fourier(x,y,dt):
  # remove the mean of both signals
  x=x-np.mean(x)
  y=y-np.mean(y)
  # compute fft
  X=np.fft.fft(x)
  Y=np.fft.fft(y)
  # Compute the cross-correlation and auto-correlation vectors
  Cxx, Cyy, Cxy=[],[],[]
  Cxy=np.conjugate(X)*Y
  Cxx=np.conjugate(X)*X
  Cyy=np.conjugate(Y)*Y
  f=np.fft.fftfreq(len(x),d=dt)
  return Cxy, Cxx, Cyy, f

def corr_time(Cxy, Cxx, Cyy, dt, v):
  cxy=np.fft.ifft(Cxy)
  cxx=np.fft.ifft(Cxx)
  cyy=np.fft.ifft(Cyy)
  # time vector
  tc=np.arange(-np.floor(len(cxy)/2)*dt,np.floor(len(cxy)/2)*dt+dt,dt)
  # normalize the cross-correlation vector (cf Schwartz inequality)
  cxy=cxy/np.sqrt(cxx[0]*cyy[0])
  # rewrite the cross-correlation vector cxy in proper order
  cxy[len(cxy)/2+1:len(cxy)]=cxy[-1:-len(cxy)/2:-1] # "positive" part
  cxy[0:len(cxy)/2+1]=cxy[-len(cxy)/2:-len(cxy)-1:-1] # "negative" part
  if v:
    fig = plt.figure()
    fig.set_facecolor('white')
    plt.plot(cxy,'k')
    #plt.show()
  value_t=np.abs(np.max(cxy))
  tau_t=tc[np.argmax(cxy)]
  return value_t, tau_t

def corr_freq(f,Cxy,v):
  # Determine the limits of the amplitude spectrum
  mini, maxi=cum(np.abs(Cxy[0:len(f)/2]),v)
  fmin, fmax = f[mini], f[maxi]
  f_min_max=f[mini:maxi]
  # Plot
  if v:
    display(Cxy,f,0,f_min_max)
    plt.show()

  # Compute the slope of the phase spectrum where the amplitude is strong...
  # This is only performed after time-realignment - do not unwrap the phase
  phase_min_max=np.angle(Cxy[mini:maxi],deg=False)
  a=sum(f_min_max*phase_min_max)/sum(f_min_max**2)
  # ... and deduce the time delay
  tau_f=a/(2*pi)
  return tau_f

def cum(x,v):
  s=np.cumsum(x)
  p=np.polyfit(range(len(x)), s, deg=1)
  line=p[0]*np.arange(len(x))+p[1]
  l=s-line

  ind_min=np.where(l<=0)[0][0]
  ind_max=np.where(l>=0)[0][-1]+1
  mini=np.argmin(l[ind_min:ind_max])+ind_min
  maxi=np.argmax(l[ind_min:ind_max])+ind_min

  if v:
    fig = plt.figure()
    fig.set_facecolor('white')
    plt.plot(x,'k')
    plt.plot(s,'y')
    plt.plot(line,'b')
    plt.plot(l,'r')
    plt.plot(mini,l[mini],'mo')
    plt.plot(maxi,l[maxi],'mo')
    #plt.show()

  return mini, maxi

def waveform(filename):
  wf=Waveform()
  wf.read_from_file(filename)
  name=wf.station
  val=wf.values
  dt=wf.delta
  tdeb=wf.starttime
  return val, dt, name, tdeb

def plot_waveform(x,y,dt,tau,ev1,ev2):
  t=np.arange(len(x))*dt
  fig = plt.figure()
  fig.set_facecolor('white')
  for i in range(len(tau)):
    itau=tau[i]
    ax=fig.add_subplot(len(tau),1,i+1)
    ax.plot(t,x/np.max(x))
    ax.plot(t+itau,y/np.max(y),'r')
  plt.suptitle('Event pair: (%s,%s)'%(ev1,ev2))

  fig = plt.figure()
  fig.set_facecolor('white')
  ax1=fig.add_subplot(211,title="event %s"%ev1)
  ax1.plot(t,x)
  ax2=fig.add_subplot(212,title="event: %s"%ev2)
  ax2.plot(t,y)

def display(Cxy,f,a,f_min_max):
  fig=plt.figure()
  fig.set_facecolor('white')
  ax1=fig.add_subplot(211, title="Amplitude spectrum")
  ax1.plot(f[0:len(f)/2],np.abs(Cxy[0:len(f)/2]))
  ax2=fig.add_subplot(212, title="Phase spectrum")
  ax2.plot(f[0:len(f)/2],np.angle(Cxy[0:len(f)/2],deg=False),'+')
  ax2.plot(f_min_max,a*f_min_max,'r')

def correlate(x,y,dt,v,a):
  Cxy, Cxx, Cyy, f = fourier(x,y,dt)
  if a=='t':
    corr, tau = corr_time(Cxy, Cxx, Cyy, dt, v)
    #tau=np.round(tau*100)/100
    return tau, corr
  if a=='f':
    tau = corr_freq(f,Cxy,v)
    return tau


def do_correlation_setup_and_run(opdict):

  base_path=opdict['base_path']
  verbose=opdict['verbose']

  # output directory
  output_dir=os.path.join(base_path,'out',opdict['outdir'])

  # data
  data_dir=os.path.join(base_path,'data',opdict['datadir'])
  data_glob=opdict['dataglob']
  data_files=glob.glob(os.path.join(data_dir,data_glob))
  data_files.sort()

  # location file
  locdir=os.path.join(base_path,'out',opdict['outdir'],'loc')
  locfile=os.path.join(locdir,'locations.dat')

  # file containing correlation values
  coeff_file=os.path.join(locdir,opdict['xcorr_corr'])
  # file containing time delays
  delay_file=os.path.join(locdir,opdict['xcorr_delay'])

  # threshold and time window
  threshold=float(opdict['xcorr_threshold'])
  t_before=float(opdict['xcorr_before'])
  t_after=float(opdict['xcorr_after'])

  # Read location
  locs=read_locs_from_file(locfile)

  # Create 2 empty dictionnaries
  coeff={}
  delay={}
  # --------------------------------------------------------------------------------------------
  # MAIN PROGRAM : Compute the correlation value and the time delay for each possible event pair

  tref=time.time()
  for file in data_files:
    event=0
    val_all, dt, name, tdeb = waveform(file)
    logging.info(name)

    coeff[name]=[]
    delay[name]=[]

    for loc_a in locs:
      event=event+1
      stack_time=loc_a['o_time']-tdeb

      start_time=int(round((stack_time-t_before)*1./dt))
      end_time=int(round((stack_time+t_after)*1./dt))
      val1=val_all[start_time-1:end_time]

      compteur=event-1

      liste, list_tau=[], []
      # Add zeros to liste as we only compute a semi matrix
      liste.extend(np.zeros(event-1))
      list_tau.extend(np.zeros(event-1))

      for loc_b in locs[event-1:]: # for every event occurring after the event "event" ; replace by event-1 if the autocorrelation is considered
        compteur=compteur+1
        stack_time_2=loc_b['o_time']-tdeb
        start_time_2=int((stack_time_2-t_before)*1./dt)
        end_time_2=int((stack_time_2+t_after)*1./dt)

        val2=val_all[start_time_2-1:end_time_2]

        if not val1.any() or not val2.any():
          liste.append('NaN')
          list_tau.append('NaN')
        else:
          tau, value = correlate(val1, val2, dt, verbose, 't')
          if value > threshold and event != compteur:
            ntau=int(round(tau*1./dt))
            val3=val_all[start_time_2-ntau-1:end_time_2-ntau]

            tau_t=tau
            tau = correlate(val1, val3, dt, verbose, 'f')
            tau=tau_t+tau

            if verbose:
              tau_f=tau
              plot_waveform(val1,val2,dt,[tau_t,tau_f],event,compteur)
              print "time: %.4f, %.4f"%(value, tau_t)
              print "frequency : %.4f, %.4f"%(value, tau_f)
              print "final delay : %.4f"%tau
              plt.show()

          liste.append(round(value*10**2)/10**2)
          if tau.size:
            list_tau.append(round(tau*10**4)/10**4)
          else:
            list_tau.append('NaN')

      coeff[name].append(liste)
      delay[name].append(list_tau)

  print "Elapsed time: ",time.time()-tref

  # Save the results in 2 binary files
  logging.info("Saving coeff and delay files")
  a=BinaryFile(coeff_file)
  a.write_binary_file(coeff)

  b=BinaryFile(delay_file)
  b.write_binary_file(delay)


if __name__ == '__main__' :

  from options import WavelocOptions

  logging.basicConfig(level=logging.INFO, format="%(levelname)s : %(asctime)s : %(message)s")

  wo = WavelocOptions()
  args=wo.p.parse_args()

  wo.set_all_arguments(args)
  wo.verify_correlation_options()

  do_correlation_setup_and_run(wo.opdict)
