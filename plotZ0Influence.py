#! /usr/bin/env python
# -*- coding: utf-8 -*-

import sys, math, os
from os import path
from numpy import *
from pylab import *
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import os,glob,subprocess
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib import rc
from Davenport import Davenport
import pdb
b = pdb.set_trace

def main(target, yM, UM, flatFlag, show, sampleFlagg):
	colorVec = ['r','k','b']
	line1 = [0,0,0]
 	dirNameList = [x for x in glob.glob(target+'*') if not x.endswith('Crude')]
	pdf = PdfPages('results_ym_' + str(yM) + '_Um_' + str(UM) + '.pdf')
	d = pdf.infodict()
	d['ModDate'] = datetime.datetime.today()
	
 	# defining output parameters
	lenList = len(dirNameList)
	AR = zeros(lenList,int)
	h = zeros(lenList,int)
	z0 = zeros(lenList,float)
 	dirNameLegend = range(lenList)

	for i, dirName in enumerate(dirNameList):
		ARs = dirName.find('_AR')
		ARe = ARs+dirName[ARs:].find('.')
		AR[i] = int(dirName[ARs+4:ARe])
		z0s = dirName.find('z0')
		z0[i] = float(dirName[z0s+3:])	
	ARvec = unique(AR)
	ARvec.sort()
	if flatFlag:
		ARvec[len(ARvec)-1]=25
	z0Vec = unique(z0)
	Umat43 , Umat2 = zeros([len(ARvec),3],float), zeros([len(ARvec),3],float)	
	Umat = zeros([len(ARvec),3,5000])
	
	import matplotlib.cm as mplcm
	import matplotlib.colors as colors
	import numpy as np

	NUM_COLORS=len(ARvec)
	cm = plt.get_cmap('jet')
	cNorm  = colors.Normalize(vmin=0, vmax=NUM_COLORS-1)
	scalarMap = mplcm.ScalarMappable(norm=cNorm, cmap=cm)

	# sorting
	temp = zip(AR,dirNameList)
	temp.sort()
	dirNameList = [x[1] for x in temp]

	for i, dirName in enumerate(dirNameList):
		ARs = dirName.find('_AR')
		ARe = ARs+dirName[ARs:].find('.')
		AR[i] = int(dirName[ARs+4:ARe])
		z0s = dirName.find('z0')
		z0[i] = float(dirName[z0s+3:])	
		hs = dirName.find('_h_')
		he = hs+dirName[hs:].find('_AR')
		if AR[i]==1000:
			h[i] = 0
		else:
			h[i] = int(dirName[hs+3:he])
		
	if sampleFlag:
		# sample results
		dirNameList = glob.glob(target + "*")
		dirNameList.sort()
		for dirName in dirNameList:
			# changing sample dictionary
			from PyFoam.RunDictionary.ParsedParameterFile 	import ParsedParameterFile
			b()
			sampleDict = ParsedParameterFile(path.join(dirName,"/system/sampleDict"))
			
			hmin = sampleDict["sets"]["line_y"]["start"](1)
			sampleDict["sets"]["line_y"]["end"] = "( 0 " + str(hmin+150) + " 0 )"
			sampleDict.writeFile()
 			# sampling
 			arg = " -case " + dirName + "/"
 			sampleRun = BasicRunner(argv=["sample -latestTime" + arg],silent=True,server=False,logname="sampleLog")
			sampleRun.start()
	# reading data
 	for i, dirName in enumerate(dirNameList):
		ARcurrent = ARvec[i//3]
		# finding the most converged run.
  		setName = glob.glob(dirName + '/sets/*')
  		lastRun = range(len(setName))
  		for num in range(len(setName)):
   			lastRun[num] = int(setName[num][setName[num].rfind("/")+1:])
  		m = max(lastRun)
  		p = lastRun.index(m)
  		
  		# output to screen of convergence data
  		if not(m % 10):
   			print dirName + " did not converge, after " + str(m) + " iterations the error is TODO"
  		else:
   			print dirName + " converged after " + str(m) + " iterations"

		# y line
		# assuming all runs are with the same z0 range and different z0. so expecting three z0 numbers
		# and assuming the sorting is according to name defined by : caseStr = "_AR_" + str(AR) + "_z0_" + str(z0)
		
  		data_y = genfromtxt(setName[p] + '/line_y_U.xy',delimiter=' ')
  		y, Ux_y, Uy_y  = data_y[:,0], data_y[:,1], data_y[:,2]
		y = y-y[0] # normalizing data to height of hill-top above ground
			   # new -       2/9/12 - using y[0] instead of h[i]
		y5000 = linspace(y[0],y[len(y)-1],5000)
		Ux_y = interp(y5000,y,Ux_y)
		y = y5000
		# applying linear factor to dictate Um at yM
		Ux_yM = interp(yM,y,Ux_y)
		
		Ux_y = Ux_y * UM/Ux_yM # normalizing speed to UM at yM
		
		# y line
		# assuming all runs are with the same z0 range and different z0. so expecting three z0 numbers
		# and assuming the sorting is according to name defined by : caseStr = "_AR_" + str(AR) + "_z0_" + str(z0)
		
  		data_inlet = genfromtxt(setName[p] + '/line_inlet_U.xy',delimiter=' ')
  		y_inlet, Ux_inlet, Uy_inlet  = data_inlet[:,0], data_inlet[:,1], data_inlet[:,2]
		Ux_inlet = Ux_inlet * UM/Ux_yM # normalizing speed to UM at yM above hill
		
		# calculating speed increase factor
		S = 0
		Ux_inlet_interp = interp(y,y_inlet,Ux_inlet)
		S = (Ux_y - Ux_inlet_interp)/Ux_inlet_interp
		
		# plotting Uy
		fig1 = plt.figure(1)
		ax1 = fig1.add_subplot(3,1+len(ARvec)//3,1+i//3)
		ax1.plot(Ux_y,y,color = colorVec[i%3])
		plt.grid(which='major')
		plt.grid(which='minor')
		plt.hold(True)
		if AR[i] == 1000:
			plt.title('flat plane')
		else:
			plt.title('AR ' + str(ARcurrent))
		if i%3==0:
			plt.ylabel('y [m]')
		if i>(len(ARvec)-2):
			plt.xlabel('Uy [m/s]')
		plt.tight_layout()
		xticks = linspace(0,round(UM*1.2),round(UM*1.2)+1)
		plt.xticks(xticks)
		fig1.set_facecolor('w') 
		
		# plotting S_y on top of hill
		fig2 = plt.figure(2)
		ax2 = plt.subplot(3,1+len(ARvec)//3,1+i//3)
		ax2.plot(S,y,color = colorVec[i%3])
		plt.grid(which='major')
		plt.grid(which='minor')
		plt.hold(True)
		if AR[i] == 1000:
			plt.title('flat plane')
		else:
			plt.title('AR ' + str(ARcurrent))
		if i%3==0:
			plt.ylabel('y [m]')
		if i>(len(ARvec)-1):
			plt.xlabel('S')
		plt.axis([0,1,max(min(y),0),max(y)])
		xticksS = [0,0.25,0.5,0.75,1]
		plt.xticks(xticksS)
		fig2.set_facecolor('w')
		
		# saving data - assuming sorted!
		# mat43 or mat2 contain rows of : [minus, orig, plus] for each AR
		Umat43[i//3,i%3] 		= interp(yM*4/3,y,Ux_y)
		Umat2[i//3,i%3] 		= interp(yM*2,y,Ux_y)
		if i==0:
			Umat = zeros([len(ARvec),3,len(y)])
		Umat[i//3,i%3,:]			= Ux_y
	

	# adding legend
	ax1.legend([str(z0Vec[0]),str(z0Vec[1]),str(z0Vec[2])],bbox_to_anchor=(1.25, 0.), loc='lower left', borderaxespad=0., title='z0 [m]')
	fig1.suptitle('Horizontal wind shear above hill\nHill shape Martinez 2011, h = ' + str(h[0]) + '[m], $y_{m}$ = ' + str(yM) + ' [m]',fontsize=16)
	fig1.tight_layout()
	fig1.subplots_adjust(top=0.85)
	pdf.savefig(fig1)
	
	ax2.legend([str(z0Vec[0]),str(z0Vec[1]),str(z0Vec[2])],bbox_to_anchor=(1.25, 0.), loc='lower left', borderaxespad=0., title='z0 [m]')
	fig2.suptitle('Accelaration above hill\nHill shape Martinez 2011, h = ' + str(h[0]) + '[m]',fontsize=16)
	fig2.tight_layout()
	fig2.subplots_adjust(top=0.85)
	pdf.savefig(fig2)
	
	#plotting error vs. z/h for different AR
	fig3 = plt.figure(3);
	for i, ARi in enumerate(ARvec):
	
		# err_plus
		ax = fig3.add_subplot(3,1,1)
		plt.title('error from picking higher z0')
		color = cm(1.*i/NUM_COLORS)  # color will now be an RGBA tuple
		if i==len(ARvec)-1 and flatFlag:
			ARlabel = 'flat'
		else:
			ARlabel = str(ARi)
		err_plus = (Umat[i,2,:]-Umat[i,1,:])/Umat[i,1,:]	*100
		plt.plot(err_plus,y,color=color,label=ARlabel)
		plt.axis([-10,10,yM,max(y)])
		xticks = [0,1,2,3,4,5]
		plt.xticks(xticks)
		plt.grid(which='major')
		
		# err_minus
		ax3 = fig3.add_subplot(3,1,2)
		plt.title('error from picking lower z0')
		color = cm(1.*i/NUM_COLORS)  # color will now be an RGBA tuple
		err_minus = (Umat[i,0,:]-Umat[i,1,:])/Umat[i,1,:]	*100
		plt.plot(err_minus,y,color=color,label=ARlabel)
		plt.ylabel('y [m]')
		plt.axis([-10,10,yM,max(y)])
		xticks = [-5,-4,-3,-2,-1,0]
		plt.xticks(xticks)
		plt.grid(which='major')
		
		# sum of errors
		ax = fig3.add_subplot(3,1,3)
		plt.title('sum of z0 induced error')
		plt.xlabel('error %');
		color = cm(1.*i/NUM_COLORS)  # color will now be an RGBA tuple
		err = abs(err_minus)+abs(err_plus)
		plt.plot(err,y,color=color,label=ARlabel)
		plt.axis([-10,10,yM,max(y)])
		fig3.set_facecolor('w')
		plt.tight_layout()
		xticks = [0,1,2,3,4,5,6,7,8]
		plt.xticks(xticks)
		plt.grid(which='major')
		
	l = ax3.legend(title='AR',loc=6,bbox_to_anchor=(0.05, 0.55))
	l.set_zorder(100)
	fig3.suptitle('Errors above hill\nHill shape Martinez 2011, h = ' + str(h[0]) + '[m], $y_{m}$ = ' + str(yM) + ' [m]',fontsize=16)
	plt.tight_layout()
	plt.subplots_adjust(top=0.85)
	pdf.savefig()
	
	# plotting S vs. AR for different z/h	
	
			
	# calculating errors
	err43_plus 	= (Umat43[:,2]-Umat43[:,1])/Umat43[:,1]	*100
	err43_minus = (Umat43[:,0]-Umat43[:,1])/Umat43[:,1]	*100
	err2_plus 	= (Umat2[:,2]-Umat2[:,1])/Umat2[:,1]	*100
	err2_minus 	= (Umat2[:,0]-Umat2[:,1])/Umat2[:,1]	*100

	# plotting err
	fig4 = figure(10,figsize=(14,8))
	ax = subplot(2,1,1)
	plt.hold(True)
	bark = plt.bar(ARvec,err43_plus ,width=0.25,color='k') 
	barr = plt.bar(ARvec+0.5,err2_plus  ,width=0.25,color='r')
	plt.bar(ARvec+0.25,err43_minus,width=0.25,color='k') 
	plt.bar(ARvec+0.75,err2_minus ,width=0.25,color='r')
	plt.grid(which='major')
	plt.grid(which='minor')

	plt.suptitle('z0 induced error for extrapolation of velocity measurement above hill center',fontsize=16)
	plt.title('Martinez2011 hill shape. Nominal z0 = ' + str(z0Vec[1]) + ' and z0 error from ' + str(z0Vec[0]) + ' to ' + str(z0Vec[2]) + '[m]')
	plt.xlabel('AR')
	plt.ylabel('error [%]') 

	# theoretical error for flat terrain
	theo_plus_2 	= ((log(yM*2/z0Vec[2])*log(yM/z0Vec[1]))/(log(yM/z0Vec[2])*log(yM*2/z0Vec[1]))-1)*100					# [m]
	theo_plus_43 	= ((log(yM*4./3./z0Vec[2])*log(yM/z0Vec[1]))/(log(yM/z0Vec[2])*log(yM*4./3./z0Vec[1]))-1)*100				# [m]
	theo_minus_2 	= ((log(yM*2/z0Vec[0])*log(yM/z0Vec[1]))/(log(yM/z0Vec[0])*log(yM*2/z0Vec[1]))-1)*100					# [m]
	theo_minus_43 	= ((log(yM*4./3./z0Vec[0])*log(yM/z0Vec[1]))/(log(yM/z0Vec[0])*log(yM*4./3./z0Vec[1]))-1)*100				# [m]
	
	plt.bar(30,theo_plus_43 ,width=0.25,color='k',edgecolor='g')
	plt.bar(30.25,theo_minus_43,width=0.25,color='k',edgecolor='g') 
	plt.bar(30.5,theo_plus_2  ,width=0.25,color='r',edgecolor='g')
	plt.bar(30.75,theo_minus_2 ,width=0.25,color='r',edgecolor='g')
	xticks = [1,3,5,8,16,25,30]
	plt.xticks(xticks,['1','3','5','8','16','flat plane','theory'])
		
	subplot(2,1,2)
	plt.hold(True)
	plt.bar(ARvec,err43_plus-err43_minus ,width=0.25,color='k') 
	plt.bar(ARvec+0.25,err2_plus-err2_minus,width=0.25,color='r') 
	plt.grid(which='major')
	plt.grid(which='minor')
	plt.xlabel('AR')
	plt.ylabel('Absolute error sum [%]')
	plt.subplots_adjust(bottom=0.25)
	plt.legend((bark[0], barr[0]),(r'$\frac{4}{3}\cdot y_m$',r'$2\cdot y_m$'),loc='lower center',bbox_to_anchor=(0.45, -0.8),title=(r'$y_m$=')+str(yM)+' [m], h='+str(h[0])+(r' [m] $\frac{y_m}{h}$=') + str(yM/h[0]) ) 

	plt.bar(30,theo_plus_43-theo_minus_43 ,width=0.25,color='k',edgecolor='g')
	plt.bar(30.25,theo_plus_2-theo_minus_2  ,width=0.25,color='r',edgecolor='g')
	plt.xticks(xticks,['1','3','5','8','16','flat plane','theory'])
	fig4.set_facecolor('w') 
	pdf.savefig()
	
	# thismanager = get_current_fig_manager()
	# thismanager.window.SetPosition((500, 0))

	# plotting S
	pdf.close()
	if show:
		plt.show()
	
	
if __name__ == '__main__':
	# reading arguments
	n = len(sys.argv)
	if n<7:
		print "Need <TARGET> <yM> <UM> <flatFlag> <show> <sampleFlag>"
		sys.exit(-1)
	target    	= sys.argv[1]
	yM 	  		= float(sys.argv[2])
	UM    		= float(sys.argv[3])
	flatFlag 	= float(sys.argv[4])
	show 	  	= float(sys.argv[5])
	sampleFlag 	= float(sys.argv[6])
	main(target, yM, UM, flatFlag,show, sampleFlag)
