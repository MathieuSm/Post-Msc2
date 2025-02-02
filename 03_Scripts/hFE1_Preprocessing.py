#%% #!/usr/bin/env python3
# Initialization

Version = '02'

Description = """
    This script runs ACCURATE pipeline without PSL
    Converted from Denis's hFE accurate pipeline
    Add Michi improvements (use of numba)

    Meant to be run locally from the FRACTIB root folder

    Author: Mathieu Simon
            ARTORG Center for Biomedical Engineering Research
            SITEM Insel, University of Bern

    Date: October 2021
    """

#%% Modules import
import os
import re
import vtk
import sys
import copy
import yaml
import scipy
import socket
import struct
import argparse
import fileinput
import numpy as np
from numba import njit
from pathlib import Path
from numba.typed import List
import matplotlib.pyplot as plt
from matplotlib import image as im
from vtk.numpy_interface import dataset_adapter as dsa # type: ignore
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk # type: ignore

from Utils import *

if os.name == 'posix':
    import resource
elif os.name == 'nt':
    import psutil

#%% Image function
# Image functions
def ReadConfigFile(Filename):

    """ Read configuration file and store to dictionary """

    with open(Filename, 'r') as File:
        Configuration = yaml.load(File, Loader=yaml.FullLoader)

    return Configuration
def Set_FileNames(Config, Sample, Directories):

    """
    Adapted from Denis's io_utils_SA.py
    Set filenames for each grayscale file
    Filenames depend on pipeline (fast/accurate)
    Always:
        - Native image for header
        - BMD or Native image cropped to ROI
    Additional for fast pipeline:
        - Periosteal mask
    Additional for accurate pipeline:
        - Trabecular mask
        - Cortical mask
        - Two-phase segmentation
    """

    # Always, not depending on phase (accurate or fast)
    Folder_IDs = Config['Folder_IDs']
    Folder = Folder_IDs[Sample]

    FileName = {}

    # Additional for accurate pipeline
    Postfix_CortMask = Config['Postfix_CortMask']
    Postfix_TrabMask = Config['Postfix_TrabMask']
    Postfix_BMD = Config['Postfix_BMD']
    Postfix_SEG = Config['Postfix_SEG']

    FileName['FILEMASKCORT'] = "{}{}".format(Sample, Postfix_CortMask)
    FileName['FILEMASKTRAB'] = "{}{}".format(Sample, Postfix_TrabMask)
    FileName['FILEBMD'] = "{}{}".format(Sample, Postfix_BMD)
    FileName['FILESEG'] = "{}{}".format(Sample, Postfix_SEG)

    # Always, not depending on phase (accurate or fast)
    FileName['FILEGRAY'] = FileName['FILEBMD']
    FileName['RAWname'] = str(Directories['AIM'] / Folder / FileName['FILEGRAY'])
    FileName['BMDname'] = str(Directories['AIM'] / Folder / FileName['FILEBMD'])

    FileName['CORTMASKname'] = str(Directories['AIM'] / Folder / FileName['FILEMASKCORT'])
    FileName['TRABMASKname'] = str(Directories['AIM'] /Folder / FileName['FILEMASKTRAB'])
    FileName['SEGname'] = str(Directories['AIM'] / Folder / FileName['FILESEG'])

    # FEA filenames
    if Config['Echo'] == True:
        print(FileName['BMDname'])
    New_FileName = "{}.inp".format('Simulation')
    FileName["INPname"] = str(Directories['FEA'] / Folder / New_FileName)

    New_FileName = "{}_Summary.txt".format(Folder)
    FileName['SummaryName'] = str(Directories['FEA'] / Folder / New_FileName)

    FileName['BCs'] = str(Directories['FEA'] / Folder / 'Loading.inp')

    # Common area
    FileName['Common'] = str(Directories['FEA'] / Folder / 'CommonMask.mhd')
    FileName['Common_uCT'] = str(Directories['Localization'] / Folder / 'CommonMask.mhd')

    # Transform parameters
    FileName['InitialTransform'] = str(Directories['Localization'] / Folder / 'InitialTransform.txt')
    FileName['Transform'] = str(Directories['Localization'] / Folder / 'TransformParameters.0.txt')

    return FileName
def Print_Memory_Usage():

    if os.name == 'posix':
        Memory_Used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1e-6
        print("Memory usage: {:.2f} (GB)".format(Memory_Used))

    elif os.name == 'nt':
        Memory_Used = psutil.virtual_memory().used * 1e-9
        print("Memory usage: {:.2f} (GB)".format(Memory_Used))
        
    return
def Get_AIM_Ints(f):

    """
    Function by Glen L. Niebur, University of Notre Dame (2010)
    reads the integer data of an AIM file to find its header length
    """

    nheaderints = 32
    nheaderfloats = 8
    f.seek(0)
    binints = f.read(nheaderints * 4)
    header_int = struct.unpack("=32i", binints)

    return header_int
def AIMReader(File, Spacing, Echo=False):

    """
    Reads an AIM file and provides
    the corresponding vtk image with spacing,
    calibration data and header
    """

    # read header
    if Echo:
        print('\n\nRead AIM header of file: ' + File)
    with open(File, 'rb') as f:
        AIM_Ints = Get_AIM_Ints(f)
        # check AIM version
        if int(AIM_Ints[5]) == 16:
            if Echo:
                print("     -> version 020")
            if int(AIM_Ints[10]) == 131074:
                Format = "short"
                if Echo:
                    print("     -> format " + Format)
            elif int(AIM_Ints[10]) == 65537:
                Format = "char"
                if Echo:
                    print("     -> format " + Format)
            elif int(AIM_Ints[10]) == 1376257:
                Format = "bin compressed"
                if Echo:
                    print("     -> format " + Format + " not supported! Exiting!")
                exit(1)
            else:
                Format = "unknown"
                if Echo:
                    print("     -> format " + Format + "! Exiting!")
                exit(1)
            Header = f.read(AIM_Ints[2])
            Header_Length = len(Header) + 160
            Extents = (0, AIM_Ints[14] - 1, 0, AIM_Ints[15] - 1, 0, AIM_Ints[16] - 1)
        else:
            if Echo:
                print("     -> version 030")
            if int(AIM_Ints[17]) == 131074:
                Format = "short"
                if Echo:
                    print("     -> format " + Format)
            elif int(AIM_Ints[17]) == 65537:
                Format = "char"
                if Echo:
                    print("     -> format " + Format)
            elif int(AIM_Ints[17]) == 1376257:
                Format = "bin compressed"
                if Echo:
                    print("     -> format " + Format + " not supported! Exiting!")
                exit(1)
            else:
                Format = "unknown"
                if Echo:
                    print("     -> format " + Format + "! Exiting!")
                exit(1)
            Header = f.read(AIM_Ints[8])
            Header_Length = len(Header) + 280
            Extents = (0, AIM_Ints[24] - 1, 0, AIM_Ints[26] - 1, 0, AIM_Ints[28] - 1)

    # collect data from header if existing
    # header = re.sub('(?i) +', ' ', header)
    Header = Header.split('\n'.encode())
    Header.pop(0)
    Header.pop(0)
    Header.pop(0)
    Header.pop(0)
    Scaling = None
    Slope = None
    Intercept = None
    IPLPostScanScaling = 1
    for Line in Header:
        if Line.find(b"Orig-ISQ-Dim-p") > -1:
            origdimp = ([int(s) for s in Line.split(b" ") if s.isdigit()])

        if Line.find("Orig-ISQ-Dim-um".encode()) > -1:
            origdimum = ([int(s) for s in Line.split(b" ") if s.isdigit()])

        if Line.find("Orig-GOBJ-Dim-p".encode()) > -1:
            origdimp = ([int(s) for s in Line.split(b" ") if s.isdigit()])

        if Line.find("Orig-GOBJ-Dim-um".encode()) > -1:
            origdimum = ([int(s) for s in Line.split(b" ") if s.isdigit()])

        if Line.find("Scaled by factor".encode()) > -1:
            # if not Scaling:
            Scaling = float(Line.split(" ".encode())[-1])
        if Line.find("Density: intercept".encode()) > -1:
            Intercept = float(Line.split(" ".encode())[-1])
        if Line.find("Density: slope".encode()) > -1:
            Slope = float(Line.split(" ".encode())[-1])
        # if el_size scale was applied, the above still takes the original voxel size. This function works
        # only if an isotropic scaling was applied!!!!
        if Line.find("downscaled".encode()) > -1:
            pass
        elif Line.find("scale".encode()) > -1:
            IPLPostScanScaling = float(Line.split(" ".encode())[-1])
    # Spacing is calculated from Original Dimensions. This is wrong, when the images were coarsened and
    # the voxel size is not anymore corresponding to the original scanning resolution!

    try:
        Spacing = IPLPostScanScaling * (
            np.around(np.asarray(origdimum) / np.asarray(origdimp) / 1000, 5)
        )
    except:
        pass
    # read AIM
    Reader = vtk.vtkImageReader2()
    Reader.SetFileName(File)
    Reader.SetDataByteOrderToLittleEndian()
    Reader.SetFileDimensionality(3)
    Reader.SetDataExtent(Extents)
    Reader.SetHeaderSize(Header_Length)
    if Format == "short":
        Reader.SetDataScalarTypeToShort()
    elif Format == "char":
        Reader.SetDataScalarTypeToChar()
    Reader.SetDataSpacing(Spacing)
    Reader.Update()
    VTK_Image = Reader.GetOutput()
    return VTK_Image, Spacing, Scaling, Slope, Intercept, Header
def Read_Image_Parameters(FileNames, Bone, Echo=False):

    """
    Read image parameters from AIM image header.
    Input: AIM image (Scanco Medical)
    Output: (bone dictionary)
    - Spacing
    - Scaling
    - Slope
    - Intercept
    """

    if Echo:
        print("\n\nRead AIM files")

    VTK_Image, Spacing, Scaling, Slope, Intercept, Header = AIMReader(FileNames["RAWname"], 0)

    Bone['Spacing'] = Spacing
    Bone['Scaling'] = Scaling
    Bone['Slope'] = Slope
    Bone['Intercept'] = Intercept

    return Bone
def VTK2Numpy(VTK_Image):

    """ Turns a vtk image data into a numpy array """

    Dimension = VTK_Image.GetDimensions()
    Data = VTK_Image.GetPointData().GetScalars()
    Numpy_Image = vtk_to_numpy(Data)
    # vtk and numpy have different array conventions
    Numpy_Image = Numpy_Image.reshape(Dimension[2], Dimension[1], Dimension[0])
    Numpy_Image = Numpy_Image.transpose(2, 1, 0)
    # y symmetry
    Numpy_Image = Numpy_Image[:,::-1,:]
    
    return Numpy_Image
def Read_AIM(Name, FileNames, Bone, Echo=False):

    """
    Read AIM image
    Adapted from Denis's io_utils_SA.py
    --------------
    All necessary AIM files are imported and stored in Bone dict
    Input: name specifier, FileNames dict, Bone dict
    Output: Bone dict
    - numpy array containing AIM image
    """

    if Echo:
        print("\n\nRead AIM file :" + Name)

    Spacing = Bone["Spacing"]
    # Read image as vtk
    VTK_Image = AIMReader(FileNames[Name + 'name'], Spacing)[0]
    # convert AIM files to numpy arrays
    IMG_Array = VTK2Numpy(VTK_Image)
    if Name == 'SEG':
        IMG_Array[IMG_Array == 127] = 2
        IMG_Array[IMG_Array == 126] = 1
        Bone[Name + '_Array'] = IMG_Array
    else:
        Bone[Name + '_Array'] = IMG_Array

    return Bone
def Adjust_Image_Size(Image, CoarseFactor, CropZ='Crop'):

    """
    Adapted from Denis's utils_SA.py
    Images are adjusted according to CropType:
    0 = CropType.expand     (Expand image by copying layers)
    1 = CropType.crop       (Crop image)
    2 = CropType.variable   (Either crop or expand, depending on what includes less layers)
    """

    # Measure image shape
    IMDimX = np.shape(Image)[0]
    IMDimY = np.shape(Image)[1]
    IMDimZ = np.shape(Image)[2]

    AddDimX = CoarseFactor - (IMDimX % CoarseFactor)
    AddDimY = CoarseFactor - (IMDimY % CoarseFactor)

    # adjust in x and y direction
    Shape_Diff = [AddDimX, AddDimY]
    IMG_XY_Adjusted = np.lib.pad(Image,
                                 ((0, Shape_Diff[0]), (0, Shape_Diff[1]), (0, 0)),
                                 'constant', constant_values=(0),)

    if CropZ == 'Crop':
        Image_Adjusted = IMG_XY_Adjusted

    if CropZ == 'Expand':
        AddDimZ = CoarseFactor - (IMDimZ % CoarseFactor)
        Shape_Diff = [AddDimX, AddDimY, AddDimZ]
        Image_Adjusted = np.lib.pad(IMG_XY_Adjusted,
                                    ((0, 0), (0, 0), (0, Shape_Diff[2])),
                                    'edge')

    if CropZ == 'Variable':
        Limit = CoarseFactor / 2.0
        if IMDimZ % CoarseFactor > Limit:
            AddDimZ = CoarseFactor - (IMDimZ % CoarseFactor)
            Shape_Diff = [AddDimX, AddDimY, AddDimZ]
            Image_Adjusted = np.lib.pad(IMG_XY_Adjusted,
                                        ((0, 0), (0, 0), (0, Shape_Diff[2])),
                                        'edge')
        if IMDimZ % CoarseFactor < Limit:
            Image_Adjusted = IMG_XY_Adjusted

    return Image_Adjusted
def Adjust_Image(Name, Bone, Config, CropType='Crop'):

    """
    Adapted from Denis's preprocessing_SA.py
    Adjust image size to current FE element size,
    that no layers of the image are removed, size in z direction has to fit.
    If empty layers are added in this dimension,
    this will create a weak layer at the bottom of the image.
    Expansions in x and y dimension,
    will probably not affect strength, but will lower stiffness.

    """

    # get bone values
    IMG_array = Bone[Name + '_Array']
    Spacing = Bone['Spacing']

    # coarsening factor = FE element size / CT voxel size
    CoarseFactor = int(round(Config['ElementSize'] / Spacing[0]))
    FEelSize = np.copy(Spacing) * CoarseFactor

    # Adjustment for BMD image and Mask
    IMG_Array_Adjusted = Adjust_Image_Size(IMG_array, CoarseFactor, CropZ=CropType)

    # For XCTI added by MI
    if Spacing[0] == 0.082:
        Height = IMG_array.shape[2] * Spacing[0]
        ElementNumber = np.rint(Height / Config['ElementSize'])
        CoarseFactor = IMG_array.shape[2] / ElementNumber
        FEelSize = np.copy(Spacing) * CoarseFactor

    # Set bone values
    # copy old IMG_array to IMG_array_original and store new adjusted IMG as IMG_array
    Bone[Name + '_Array_original'] = IMG_array
    Bone[Name + '_Array'] = IMG_Array_Adjusted
    Bone['FEelSize'] = FEelSize
    Bone['CoarseFactor'] = CoarseFactor

    return Bone

#%%
# Medtool functions
def ProgressStart(text):
    global curProgress
    sys.stdout.write(text + '|')
    curProgress = 0
    sys.stdout.flush()
    return
def ProgressNext(progress):
    global curProgress
    if progress > curProgress:
        curProgress += 1
        sys.stdout.write('=')
        sys.stdout.flush()
    return
def ProgressEnd():
    sys.stdout.write('|\n')
    sys.stdout.flush()
    return
def CastType(curVoxelModel, Format):
    numpyVersion = float(np.__version__[0:3])
    minVox = 10000000
    maxVox = 10000000
    if Format == 'B' or Format == 'H' or Format == 'h':
        maxVox = curVoxelModel.max()
        minVox = curVoxelModel.min()
    if Format == 'B':
        if int(minVox) < 0 or int(maxVox) > 255:
            sys.stdout.write(
                '\n **ERROR** castType(). min=%s, max=%s, format=%s!\n' % (repr(minVox), repr(maxVox), Format))
            sys.stdout.flush()
            sys.stdout.write(' *********** Use "-scale" option to scale your data from 0..255 first. \n')
            sys.stdout.flush()
            sys.stdout.write('\n E N D E D  with ERRORS \n\n')
            sys.stdout.flush()
            exit(1)
        elif numpyVersion > 1.6:
            curVoxelModel = curVoxelModel.astype('uint8', order='F')
        else:
            curVoxelModel = curVoxelModel.astype('uint8')
    elif Format == 'H':
        if int(minVox) < 0 or int(maxVox) > 65535:
            sys.stdout.write(
                '\n **ERROR** castType(). min=%s, max=%s, format=%s!\n' % (repr(minVox), repr(maxVox), Format))
            sys.stdout.flush()
            sys.stdout.write(' *********** Use "-scale" option to scale your data from 0..65535 first. \n')
            sys.stdout.flush()
            sys.stdout.write('\n E N D E D  with ERRORS \n\n')
            sys.stdout.flush()
            exit(1)
        elif numpyVersion > 1.6:
            curVoxelModel = curVoxelModel.astype('uint16', order='F')
        else:
            curVoxelModel = curVoxelModel.astype('uint16')
    elif Format == 'h':
        if int(minVox) < -32768 or int(maxVox) > 32767:
            sys.stdout.write(
                '\n **ERROR** castType(). min=%s, max=%s, format=%s!\n' % (repr(minVox), repr(maxVox), Format))
            sys.stdout.flush()
            sys.stdout.write(' *********** Use "-scale" option to scale your data from -32768..+32767 first. \n')
            sys.stdout.flush()
            sys.stdout.write('\n E N D E D  with ERRORS \n\n')
            sys.stdout.flush()
            exit(1)
        elif numpyVersion > 1.6:
            curVoxelModel = curVoxelModel.astype('int16', order='F')
        else:
            curVoxelModel = curVoxelModel.astype('int16')
    elif Format == 'i':
        if numpyVersion > 1.6:
            curVoxelModel = curVoxelModel.astype('int32', order='F')
        else:
            curVoxelModel = curVoxelModel.astype('int32')
    elif Format == 'f':
        if numpyVersion > 1.6:
            curVoxelModel = curVoxelModel.astype('float32', order='F')
        else:
            curVoxelModel = curVoxelModel.astype('float32')
    else:
        sys.stdout.write('\n **ERROR** castType(). format=%s! not implemented\n' % Format)
        sys.stdout.flush()
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        exit(1)
    return curVoxelModel
def UserSplit(oldString):
    if oldString.find(':') > -1 and oldString.find(';') > -1:
        Error = ("Option value '%s' shows a not allowed mixture of  ':' and ';' delimiters!" % oldString)
        sys.stdout.write('\n **ERROR** %s\n\n' % Error)
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        exit(1)
    newString = oldString.replace(':', ';')
    findList = re.findall('[A-Z];\\\\', newString)
    for val in findList:
        newString = newString.replace(val[0] + ';', val[0] + ':')

    findList = re.findall('[A-Z];/', newString)
    for val in findList:
        newString = newString.replace(val[0] + ';', val[0] + ':')

    return newString.split(';')
def GetFilenameAndExtension(FileName):
    """ Function returns file extension and file name. """
    Parts = FileName.split('.')
    NParts = len(Parts)
    Ext = Parts[NParts - 1]
    FileName = ''
    for Part in range(NParts - 1):
        if Part < NParts - 2:
            FileName = FileName + Parts[Part] + '.'
        else:
            FileName = FileName + Parts[Part]

    return FileName, Ext
def GetShortFilenameAndExtension(FileName):
    FileName, Ext = GetFilenameAndExtension(FileName)
    FileName = FileName.split('/')
    return FileName[len(FileName) - 1], Ext
def WriteAbaqusGeneral(outFileName, curVoxelModel, dimList, Echo=False):

    """
    Modified function of Medtool
    General Abaqus *.inp file writer. For these materials a default material will be
    applied. Supported commands:
      *USER NODE
      *USER ELEMENT
      *USER NSET, type=point, location=arbitrary
        generate NSET: ARB_NODE_S, ARB_NODE_N, ARB_NODE_E, ARB_NODE_W, ARB_NODE_T, ARB_NODE_B
      *USER NSET, type=point, location=addcorner
        generate NSET: ACOR_NODE_SWB, ACOR_NODE_SEB, ACOR_NODE_NEB, ACOR_NODE_NWB,
                       ACOR_NODE_SWT, ACOR_NODE_SET, ACOR_NODE_NET, ACOR_NODE_NWT
      *USER NSET, type=face
        generate NSET: ALL_NODE_S, ALL_NODE_N, ALL_NODE_E, ALL_NODE_W, ALL_NODE_T, ALL_NODE_B
      *USER ELSET, type=face
        generate ELSET: ALL_S, ALL_ELEM_N, ALL_ELEM_E, ALL_ELEM_W, ALL_ELEM_T, ALL_ELEM_B
      *USER PROPERTY, file=property_temp.inp, range=5:367
        generate multiple material cards, internal variables are "SetName, CardName, GrayValue"
        for the given example: GrayValues > 5 and GrayValues <= 367 are written
        This card can be used multiple times
        If range=... is not given, material cards for all GrayValues are written
    Elements are only written for the given ranges in *USER PROPERTY

    @param outFileName: name of the output file
    @param curVoxelModel: voxel model of the RVE
        - TYPE: np.array[iX, jY, kZ] = grayValue
        - int iX, jY, kZ ... voxels number ID in x,y,z start a 0, x fastest.
        - int grayValue  ... value of voxel
    @param  dimList: list of voxel dimension's
        - TYPE: list[0] = lenX, list[0] = lenY, list[0] = lenZ
        - float lenX, lenY, lenZ ... physical voxel dimensions in x,y,z
    @param  templateFile: name of the template file
    @param  smoothParam: taubin voxel model smoothing parameter
        - TYPE: list[0] = iter, list[1] = lambda, list[2] = kPB,
                list[3] = nearIntf, list[4] = bcid, list[5] = shrink
        - int iter, float lambda, float kPB, int nearIntf

    @return:
      no return value
    """
    if Echo:
        sys.stdout.write('\n\nSetup ABAQUS *.inp file from template')
        sys.stdout.write("    -> recast model from '%s' to 'i'" % curVoxelModel.dtype.char)
        sys.stdout.flush()
    curVoxelModel = CastType(curVoxelModel, 'i')
    if dimList.all() == None:  # 12.01.01 change: if dimList == None:     to if dimList.all() == None
        print('\n **ERROR** writeAbaqusGeneral(): Voxel size not optional for this function!\n')
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        exit(1)
    xvox = dimList[0]
    yvox = dimList[1]
    zvox = dimList[2]
    nz, ny, nx = curVoxelModel.shape
    minVox, maxVox = np.min(curVoxelModel), np.max(curVoxelModel)
    minVox = int(minVox + 0.5)
    maxVox = int(maxVox + 0.5)
    activeNodes = {}
    nodeSets = {}
    nodeSets['ALL_NODE_S'] = []
    nodeSets['ALL_NODE_N'] = []
    nodeSets['ALL_NODE_E'] = []
    nodeSets['ALL_NODE_W'] = []
    nodeSets['ALL_NODE_T'] = []
    nodeSets['ALL_NODE_B'] = []
    elemSets = {}
    elemSets['ALL_ELEM_S'] = []
    elemSets['ALL_ELEM_N'] = []
    elemSets['ALL_ELEM_E'] = []
    elemSets['ALL_ELEM_W'] = []
    elemSets['ALL_ELEM_T'] = []
    elemSets['ALL_ELEM_B'] = []

    tempflag = False
    OS = open('temp.inp', 'w')
    OS.write('*USER NODE\n*USER ELEMENT\n*USER PROPERTY, file=prop.inp, range=1:255\n')
    OS.close()
    OS = open('prop.inp', 'w')
    OS.write('*SOLID SECTION, ELSET=SetName, MATERIAL=CardName\n1.\n')
    OS.write('*MATERIAL,NAME=CardName\n')
    OS.write('*ELASTIC\n')
    OS.write('20000., 0.3\n')
    OS.close()
    templateFile = 'temp.inp'
    OS = open(outFileName, 'w')
    try:
        osTempFile = open(templateFile, 'r')
    except IOError:
        sys.stdout.write(
            "\n **ERROR** mic.writeAbaqusGeneral(): Abaqus Template file '%s' not found!\n\n" % templateFile)
        sys.stdout.flush()
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        exit(1)

    lines = osTempFile.readlines()
    elsetNodes = {}
    ranges = {}
    thresList = []
    rangeMin = 0
    rangeMax = 255
    outFlag = False
    overlap = np.zeros(rangeMax + 1, 'int')
    for line in lines:
        line = line.replace('\n', '')
        if line.upper().find('*USER PROPERTY') == 0:
            line = line.replace(' ', '')
            args = line.split(',')
            matTemplateFilename = ''
            for arg in args:
                if arg.upper().find('RANGE') == 0:
                    dummy, rangeStr = arg.split('=')
                    rangeMin, rangeMax = UserSplit(rangeStr)
                    rangeMin = int(rangeMin)
                    rangeMax = int(rangeMax)
                    if rangeMin < 1:
                        sys.stdout.write('\n **ERROR** mic.writeAbaqusGeneral(): Minimum Range < 1!\n\n')
                        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
                        sys.stdout.flush()
                        exit(1)
                    if rangeMax > maxVox:
                        outFlag = True
                    for ii in range(rangeMax - rangeMin + 1):
                        overlap[rangeMin + ii] += 1

                if arg.upper().find('FILE') == 0:
                    dummy, matTemplateFilename = arg.split('=')

            ranges[matTemplateFilename] = (
                rangeMin, rangeMax)

    if len(ranges) == 0:
        sys.stdout.write('\n **ERROR** mic.writeAbaqusGeneral(): *USER PROPERTY: keyword missing!\n\n')
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        exit(1)
    if rangeMax > maxVox:
        if maxVox != 1:
            sys.stdout.write(
                '\n **WARNING** mic.writeAbaqusGeneral(): *USER PROPERTY: Max GV Range (%i) > Max Image GV (%i)!\n\n' % (
                    rangeMax, maxVox))
            sys.stdout.write(outFileName)
    if np.sum(np.greater(overlap, 1)) > 0:
        sys.stdout.write(
            '\n **ERROR** mic.writeAbaqusGeneral(): *USER PROPERTY: Ranges in property template overlap!\n\n')
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        exit(1)
    for crange in ranges:
        for matId in range(ranges[crange][0], ranges[crange][1] + 1):
            # print('matID', matId)
            elsetNodes[repr(matId)] = []
            thresList.append(matId)

    elid = 0
    nx1 = nx + 1
    nxy1 = (ny + 1) * (nx + 1)
    sum = 0
    if Echo:
        ProgressStart('     -> setup Element Data  : ')
    for k in range(nz):
        sum += 1
        progress = float(sum) / float(nz) * 10.0
        for j in range(ny):
            for i in range(nx):
                grayValue = curVoxelModel[k, j, i]
                if repr(grayValue) in elsetNodes:
                    # if elsetNodes.has_key(repr(grayValue)):
                    elid = elid + 1
                    elnds = [nxy1 * k + nx1 * j + (i + 1),
                             nxy1 * k + nx1 * j + (i + 2),
                             nxy1 * k + nx1 * (j + 1) + (i + 2),
                             nxy1 * k + nx1 * (j + 1) + (i + 1),
                             nxy1 * (k + 1) + nx1 * j + (i + 1),
                             nxy1 * (k + 1) + nx1 * j + (i + 2),
                             nxy1 * (k + 1) + nx1 * (j + 1) + (i + 2),
                             nxy1 * (k + 1) + nx1 * (j + 1) + (i + 1)]
                    elsetNodes[repr(grayValue)].append((elid, elnds))
                    if k == 0:
                        elemSets['ALL_ELEM_B'].append(elid)
                    if k == nz - 1:
                        elemSets['ALL_ELEM_T'].append(elid)
                    if j == 0:
                        elemSets['ALL_ELEM_S'].append(elid)
                    if j == ny - 1:
                        elemSets['ALL_ELEM_N'].append(elid)
                    if i == 0:
                        elemSets['ALL_ELEM_W'].append(elid)
                    if i == nx - 1:
                        elemSets['ALL_ELEM_E'].append(elid)

        if Echo:
            ProgressNext(progress)

    if Echo:
        ProgressEnd()
        sys.stdout.write('     -> setup Node Data     :')
    for matid in thresList:
        if len(elsetNodes[repr(matid)]) > 0:
            matidStr = 'SET' + repr(matid)
            for elnds in elsetNodes[repr(matid)]:
                elid = elnds[0]
                for elnd in elnds[1]:
                    activeNodes[elnd] = 1

    noid = 0
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                noid = noid + 1
                if noid in activeNodes:
                    # if activeNodes.has_key(noid):
                    if k == 0:
                        nodeSets['ALL_NODE_B'].append(noid)
                    if k == nz:
                        nodeSets['ALL_NODE_T'].append(noid)
                    if j == 0:
                        nodeSets['ALL_NODE_S'].append(noid)
                    if j == ny:
                        nodeSets['ALL_NODE_N'].append(noid)
                    if i == 0:
                        nodeSets['ALL_NODE_W'].append(noid)
                    if i == nx:
                        nodeSets['ALL_NODE_E'].append(noid)

    if Echo:
        sys.stdout.write(' Done\n')
        sys.stdout.flush()
    nodeCoord = {}
    nodeCoordOrig = {}


    noid = 0
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                noid = noid + 1
                if noid in activeNodes:
                    # if activeNodes.has_key(noid):
                    nodeCoord[noid] = (
                        float(xvox * i), float(yvox * j), float(zvox * k))

    curPathFilename, ext = GetFilenameAndExtension(outFileName)
    curFilename, ext = GetShortFilenameAndExtension(outFileName)

    if Echo:
        sys.stdout.write(' ... write ABAQUS *.inp file from template\n')

    for line in lines:
        line = line.replace('\n', '')
        line = line.replace('$filename', curFilename)
        line = line.replace('$pathfilename', curPathFilename)
        if line.upper().find('*USER NODE') > -1:
            OS.write('*NODE\n')
            noid2 = 0
            noid = 0
            if Echo:
                ProgressStart('     -> process Node IDs    : ')
            for k in range(nz + 1):
                progress = float(k + 1) / float(nz + 1) * 10.0
                for j in range(ny + 1):
                    for i in range(nx + 1):
                        noid = noid + 1
                        if noid in activeNodes:
                            # if activeNodes.has_key(noid):
                            noid2 = noid2 + 1
                            OS.write('%12i,%13.6g,%13.6g,%13.6g\n' % (
                                noid, nodeCoord[noid][0], nodeCoord[noid][1], nodeCoord[noid][2]))

                if Echo:
                    ProgressNext(progress)

            if Echo:
                ProgressEnd()
                sys.stdout.write('     -> write Nodes         : %10i \n' % noid2)
                sys.stdout.flush()

        elif line.upper().find('*USER ELEMENT') > -1:
            count = 0
            if Echo:
                ProgressStart('     -> process Elements    : ')
            for matid in thresList:
                count += 1
                progress = count / float(len(thresList)) * 10.0
                if len(elsetNodes[repr(matid)]) > 0:
                    matidStr = 'SET' + repr(matid)
                    OS.write('*ELEMENT, TYPE=C3D8, ELSET=%s\n' % matidStr)
                    for elnds in elsetNodes[repr(matid)]:
                        elid = elnds[0]
                        OS.write('%s,%s,%s,%s,%s,%s,%s,%s,%s\n' % (
                            elid, elnds[1][0], elnds[1][1], elnds[1][2], elnds[1][3], elnds[1][4], elnds[1][5],
                            elnds[1][6], elnds[1][7]))
                        for elnd in elnds[1]:
                            activeNodes[elnd] = 1

                if Echo:
                    ProgressNext(progress)

            if Echo:
                ProgressEnd()
                sys.stdout.write('     -> write Elements      : %10i             \n' % elid)
                sys.stdout.flush()

        elif line.upper().find('*USER NSET') > -1:
            if line.upper().find('TYPE=FACE') > -1:
                if Echo:
                    sys.stdout.write('     -> write BCs Node Sets     \n')
                    sys.stdout.flush()
                for nsetName in nodeSets:
                    OS.write('*NSET, NSET=%s\n' % nsetName)
                    entry = 0
                    for noid in nodeSets[nsetName]:
                        entry = entry + 1
                        if entry == 16:
                            OS.write('%s' % repr(noid))
                            entry = 0
                            OS.write('\n')
                        else:
                            OS.write('%s,' % repr(noid))

                    OS.write('\n')

            if line.upper().find('TYPE=POINT') > -1:
                if line.upper().find('LOCATION=ARBITRARY') > -1:
                    for nsetName in nodeSets:
                        if len(nodeSets[nsetName]) > 0:
                            nid = nodeSets[nsetName][0]
                            name = nsetName.replace('ALL_NODE_', 'ARB_NODE_')
                            OS.write('*NSET, NSET=%s\n' % name)
                            OS.write('%s\n' % repr(nid))

                if line.upper().find('LOCATION=ADDCORNER') > -1:
                    nid = (nx + 1) * (ny + 1) * (nz + 1)
                    OS.write('*NODE, NSET=ACOR_NODE_SWB\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 1, 0.0, 0.0, 0.0))
                    OS.write('*NODE, NSET=ACOR_NODE_SEB\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 2, nx * xvox, 0.0, 0.0))
                    OS.write('*NODE, NSET=ACOR_NODE_NEB\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 3, nx * xvox, ny * yvox, 0.0))
                    OS.write('*NODE, NSET=ACOR_NODE_NWB\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 4, 0.0, ny * yvox, 0.0))
                    OS.write('*NODE, NSET=ACOR_NODE_SWT\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 5, 0.0, 0.0, nz * zvox))
                    OS.write('*NODE, NSET=ACOR_NODE_SET\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 6, nx * xvox, 0.0, nz * zvox))
                    OS.write('*NODE, NSET=ACOR_NODE_NET\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 7, nx * xvox, ny * yvox, nz * zvox))
                    OS.write('*NODE, NSET=ACOR_NODE_NWT\n')
                    OS.write('%i, %13.6g,  %13.6g, %13.6g\n' % (nid + 8, 0.0, ny * yvox, nz * zvox))
        elif line.upper().find('*USER ELSET') > -1:
            if line.upper().find('TYPE=FACE') > -1:
                if Echo:
                    sys.stdout.write('     -> Write BCs Elem Sets          \n')
                    sys.stdout.flush()
                for elsetName in elemSets:
                    OS.write('*ELSET, ELSET=%s\n' % elsetName)
                    entry = 0
                    for elid in elemSets[elsetName]:
                        entry = entry + 1
                        if entry == 16:
                            OS.write('%s' % repr(elid))
                            entry = 0
                            OS.write('\n')
                        else:
                            OS.write('%s,' % repr(elid))

                    OS.write('\n')

        elif line.upper().find('*USER PROPERTY') > -1:
            line = line.replace(' ', '')
            args = line.split(',')
            rangeMin = minVox
            rangeMax = maxVox
            matTemplateFilename = ''
            for arg in args:
                if arg.upper().find('RANGE') == 0:
                    dummy, rangeStr = arg.split('=')
                    rangeMin, rangeMax = UserSplit(rangeStr)
                    rangeMin = int(rangeMin)
                    rangeMax = int(rangeMax)
                if arg.upper().find('FILE') == 0:
                    dummy, matTemplateFilename = arg.split('=')

            if Echo:
                sys.stdout.write('     -> Write Property      : %s \n' % matTemplateFilename)
            try:
                osMatCard = open(matTemplateFilename, 'r')
            except IOError:
                sys.stdout.write(
                    "\n **ERROR** writeAbaqusGeneral(): Material template file '%s' not found!\n\n" % matTemplateFilename)
                sys.stdout.flush()
                sys.stdout.write('\n E N D E D  with ERRORS \n\n')
                sys.stdout.flush()
                exit(1)

            lines = osMatCard.readlines()
            for matid in thresList:
                GrayValue = matid
                if len(elsetNodes[repr(matid)]) > 0:
                    if matid >= rangeMin and matid <= rangeMax:
                        matidStr = 'SET' + repr(matid)
                        GrayValue = matid
                        for line in lines:
                            line = line.replace('\n', '')
                            if line.find('SetName') > -1:
                                line = line.replace('SetName', matidStr)
                            if line.find('CardName') > -1:
                                line = line.replace('CardName', 'MAT' + matidStr)
                            if line.find('GrayValue') > -1:
                                exprList = line.split(',')
                                count = 0
                                for expr in exprList:
                                    if expr.find('GrayValue') > -1:
                                        compValue = eval(expr)
                                        OS.write('%s' % repr(compValue))
                                    else:
                                        OS.write('%s' % expr)
                                    if count < len(exprList) - 1:
                                        OS.write(',')
                                    count += 1

                                OS.write('\n')
                            else:
                                OS.write('%s\n' % line)

            osMatCard.close()
        else:
            OS.write('%s\n' % line)

    osTempFile.close()
    os.remove('temp.inp')
    os.remove('prop.inp')
    OS.close
    return
def GetAbaqusArgument(string, argName):
    argument = ''
    string = string.replace('\n', '')
    STRING = string.upper()
    ARGNAME = argName.upper()
    if STRING.find(ARGNAME) > 0:
        string1 = string.split(',')
        # string1 = split(string, ',')
        for stringpart in string1:
            stringpart = stringpart.replace(' ', '')
            if stringpart.upper().find(ARGNAME) == 0:
                command, argument = stringpart.split('=')
                # command, argument = split(stringpart, '=')

    else:
        print(" **ERROR** getAbaqusArgument(): Argument '%s' not found!" % argName)
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        sys.stdout.flush()
        exit(1)
    return argument
def ReadAbaqus(inFileName, props=False, Echo=False):

    if Echo:
        print(' ... read Abaqus file       : ', inFileName)
    sys.stdout.flush()
    try:
        inStream = open(inFileName, 'r')
    except IOError:
        sys.stdout.write("\n **ERROR**: '-in' intput file '%s' not found!\n\n" % inFileName)
        sys.stdout.flush()
        sys.stdout.write('\n E N D E D  with ERRORS \n\n')
        sys.stdout.flush()
        exit(1)

    lines = []
    line = ' '
    while line != '':
        line = inStream.readline()
        if line != '':
            lines.append(line)
        LINE = line.upper()
        if LINE.find('*INCLUDE') == 0:
            inputfile = GetAbaqusArgument(line, 'INPUT')
            inStream2 = open(inputfile, 'r')
            line2 = ' '
            while line2 != '':
                line2 = inStream2.readline()
                if line2 != '':
                    lines.append(line2)
    read = False
    title = None
    nodes = {}
    elems = {}
    nsets = {}
    elsets = {}
    properties = {}
    unknownElems = []
    lineNo = 0
    while lineNo < len(lines):
        lineNo = lineNo + 1
        line = lines[lineNo - 1]
        LINE = line.upper()
        if LINE.find('*HEADING') == 0:
            lineNo = lineNo + 1
            line = lines[lineNo - 1]
            LINE = line.upper()
            title = lines[lineNo - 1]
            title = title.replace('\n', '')
        if LINE.find('*NODE') == 0 and LINE.upper().find('*NODE PRINT') == -1 and LINE.upper().find(
                '*NODE FILE') == -1 and LINE.upper().find('*NODE OUTPUT') == -1:
            nsetName = None
            if LINE.upper().find('NSET') > 0:
                nsetName = GetAbaqusArgument(line, 'NSET')
            while lineNo < len(lines):
                lineNo = lineNo + 1
                line = lines[lineNo - 1]
                if line.find('*') == 0 and line.find('**') == -1:
                    lineNo = lineNo - 1
                    break
                if line.find('**') == 0 or line.find('\n') == 0:
                    pass
                else:
                    vList = line.split(',')
                    nNo = int(vList[0])
                    curNode = Node_Class(nNo, float(vList[1]))
                    if len(vList) > 2:
                        curNode.set_y(float(vList[2]))
                    if len(vList) > 3:
                        curNode.set_z(float(vList[3]))
                    nodes[nNo] = curNode
                    if nsetName != None:
                        # if nsets.has_key(nsetName):
                        if nsetName in nsets:
                            nsets[nsetName].append(nNo)
                        else:
                            nsets[nsetName] = [nNo]

            continue
        LINE = line.upper()
        if LINE.find('*NSET') == 0:
            if Echo:
                print('  -> found *NSET    at Line %s' % repr(lineNo))
            nsetName = GetAbaqusArgument(line, 'NSET')
            while lineNo < len(lines):
                lineNo = lineNo + 1
                line = lines[lineNo - 1]
                if line.find('*') == 0 and line.find('**') == -1:
                    lineNo = lineNo - 1
                    break
                if line.find('**') == 0 or line.find('\n') == 0:
                    pass
                else:
                    line = line.replace('\n', '')
                    line = line.replace(' ', '')
                    vList = line.split(',')
                    for Id in vList:
                        if len(Id) > 0:
                            # if nsets.has_key(nsetName):
                            if nsetName in nsets:
                                nsets[nsetName].append(int(Id))
                            else:
                                nsets[nsetName] = [int(Id)]

            continue
        LINE = line.upper()
        if LINE.find('*ELEMENT') == 0 and LINE.upper().find('*ELEMENT OUTPUT') == -1:
            elType = ''
            aElType = GetAbaqusArgument(line, 'TYPE')
            aElType = aElType.upper()
            nExpNo = 0
            if aElType.find('B32') == 0:
                elType = 'bar3'
                noExpNo = 3
            elif aElType.find('B3') == 0 or aElType.find('T3') == 0:
                elType = 'bar2'
                noExpNo = 2
            elif aElType.find('CPS3') == 0 or aElType.find('CPE3') == 0 or aElType.find('S3') == 0 or aElType.find(
                    'STRI3') == 0:
                elType = 'tria3'
                noExpNo = 3
            elif aElType.find('STRI65') == 0:
                elType = 'tria6'
                noExpNo = 6
            elif aElType.find('CPS4') == 0 or aElType.find('CPE4') == 0 or aElType.find('S4') == 0:
                elType = 'quad4'
                noExpNo = 4
            elif aElType.find('CPS8') == 0 or aElType.find('CPE8') == 0 or aElType.find('S8') == 0:
                elType = 'quad8'
                noExpNo = 8
            elif aElType.find('C3D4') == 0:
                elType = 'tetra4'
                noExpNo = 4
            elif aElType.find('C3D5') == 0:
                elType = 'pyra5'
                noExpNo = 5
            elif aElType.find('C3D8') == 0 or aElType.find('SC8') == 0:
                elType = 'hexa8'
                noExpNo = 8
            elif aElType.find('C3D6') == 0 or aElType.find('SC6') == 0:
                elType = 'penta6'
                noExpNo = 6
            elif aElType.find('C3D10') == 0:
                elType = 'tetra10'
                noExpNo = 10
            elif aElType.find('C3D15') == 0:
                elType = 'penta15'
                noExpNo = 15
            elif aElType.find('C3D20') == 0:
                elType = 'hexa20'
                noExpNo = 20
            else:
                if aElType not in unknownElems:
                    unknownElems.append(aElType)
                continue
            elsetName = ''
            if LINE.find('ELSET') > 0:
                elsetName = GetAbaqusArgument(line, 'ELSET')
            while lineNo < len(lines):
                lineNo += 1
                line = lines[lineNo - 1]
                vList = []
                if line.find('*') == 0 and line.find('**') == -1:
                    lineNo = lineNo - 1
                    break
                if line.find('**') == 0 or line.find('\n') == 0:
                    pass
                else:
                    line = line.replace('\n', '')
                    line = line.replace(',', ' ')
                    vList1 = line.split()
                    # vList1 = split(line)
                    if len(vList1) - 1 != noExpNo:
                        lineNo += 1
                        line = lines[lineNo - 1]
                        line = line.replace('\n', '')
                        line = line.replace(',', ' ')
                        vList2 = line.split()
                        # vList2 = split(line)
                        if len(vList1) + len(vList2) - 1 != noExpNo:
                            lineNo += 1
                            line = lines[lineNo - 1]
                            line = line.replace('\n', '')
                            line = line.replace(',', ' ')
                            vList3 = line.split()
                            # vList3 = split(line)
                            if len(vList1) + len(vList2) + len(vList3) - 1 != noExpNo:
                                sys.stdout.write(
                                    '\n **ERROR**: fec.readAbaqus(): Line %i ff: Number of nodes for this' % (
                                            lineNo - 2))
                                sys.stdout.write('\n            element and expected nodes to not coincide !\n\n')
                                sys.stdout.write('\n E N D E D  with ERRORS \n\n')
                                sys.stdout.flush()
                                exit(1)
                            else:
                                vList = vList1 + vList2 + vList3
                        else:
                            vList = vList1 + vList2
                    else:
                        vList = vList1
                    eNo = int(vList[0])
                    nList = []
                    for nNo in range(1, len(vList)):
                        nList.append(int(vList[nNo]))

                    curElem = Element_Class(eNo, nList, elType)
                    elems[eNo] = curElem
                    if elsetName in elsets:
                        # if elsets.has_key(elsetName) > 0:
                        elsets[elsetName].append(eNo)
                    else:
                        elsets[elsetName] = [eNo]

            continue
        if LINE.find('*ELSET') == 0:
            print('\n ** WARNING ** :  *ELSET keyword not supported\n ')
        if LINE.find('*BEAM SECTION') == 0:
            elsetName = GetAbaqusArgument(line, 'ELSET')
            sectName = GetAbaqusArgument(line, 'SECTION')
            matName = GetAbaqusArgument(line, 'MATERIAL')
            if sectName.find('CIRC') == 0:
                lineNo += 1
                line = lines[lineNo - 1]
                data = line.split(',')
                if len(data) == 1:
                    radius = [float(data[0])]
                else:
                    radius = [float(data[0]), float(data[1])]
            else:
                sys.stdout.write('\n ** WARNING ** :  *BEAM SECTION, SECTION=%s not implemented\n ' % sectName)
            properties[elsetName] = {'type': 'BEAM',
                                     'material': matName,
                                     'section': sectName,
                                     'geometry': radius}
            continue
        if LINE.find('*SHELL SECTION') == 0:
            elsetName = GetAbaqusArgument(line, 'ELSET')
            matName = GetAbaqusArgument(line, 'MATERIAL')
            lineNo += 1
            line = lines[lineNo - 1]
            thickness = float(line)
            properties[elsetName] = {'type': 'SHELL',
                                     'material': matName,
                                     'thickness': thickness}
            continue
        if LINE.find('*SOLID SECTION') == 0:
            elsetName = GetAbaqusArgument(line, 'ELSET')
            matName = GetAbaqusArgument(line, 'MATERIAL')
            properties[elsetName] = {'type': 'SOLID',
                                     'material': matName}
            lineNo += 1
            continue

    if len(unknownElems) > 0:
        sys.stdout.write("\n **WARNING**: fec.readAbaqus() Element Types '%s' not implemented!\n" % str(unknownElems))
        sys.stdout.flush()
    if props == True:
        return (title,
                nodes,
                nsets,
                elems,
                elsets,
                properties)
    else:
        return (title,
                nodes,
                nsets,
                elems,
                elsets)
def WriteAbaqus(outFileName, title, nodes, nsets, elems, elsets, NscaResults=None, Echo=False):

    if Echo:
        print(' ... write ABAQUS file       : ', outFileName)
    sys.stdout.flush()
    keys = list(nodes.keys())
    nkey1 = keys[1]
    del keys
    noSpatDim = nodes[nkey1].get_dimension()
    os = open(outFileName, 'w')
    if not title == None:
        os.write('*HEADING\n')
        os.write('%s\n' % title)
    os.write('***********************************************************\n')
    os.write('*NODE\n')
    for nodeId in nodes:
        os.write('%s, ' % repr(nodeId))
        os.write('%13.7e, ' % nodes[nodeId].get_x())
        if noSpatDim > 1:
            os.write('%13.7e, ' % nodes[nodeId].get_y())
        else:
            os.write(', ')
        if noSpatDim > 2:
            os.write('%13.7e ' % nodes[nodeId].get_z())
        os.write('\n')

    if NscaResults != None:
        os.write('***********************************************************\n')
        os.write('*NODAL THICKNESS\n')
        nodeThick = NscaResults[0]
        for nodeId in nodes:
            os.write('%s, ' % repr(nodeId))
            os.write('%13.7e\n' % nodeThick[nodeId])

    os.write('***********************************************************\n')
    if nsets != None:
        if len(nsets) > 0:
            for setName in nsets:
                if setName != '':
                    os.write('*NSET, NSET=%s\n' % setName)
                    count = 0
                    for nodeId in nsets[setName]:
                        count += 1
                        if count == 16:
                            os.write('%s' % nodeId)
                            os.write('\n')
                            count = 0
                        else:
                            os.write('%s, ' % nodeId)

                    if count != 0:
                        os.write('\n')

    else:
        os.write('** no NSET written\n')
    os.write('***********************************************************\n')
    if elsets != None:
        if len(elsets) > 0:
            for setName in elsets:
                aElType = ''
                elType = elems[elsets[setName][0]].get_type()
                if elType == 'bar2':
                    aElType = 'B3'
                elif elType == 'tria3':
                    aElType = 'S3'
                elif elType == 'quad4':
                    aElType = 'S4'
                elif elType == 'penta6':
                    aElType = 'C3D6'
                elif elType == 'hexa8':
                    aElType = 'C3D8'
                elif elType == 'tetra4':
                    aElType = 'C3D4'
                elif elType == 'pyra5':
                    aElType = 'C3D5'
                elif elType == 'bar3':
                    aElType = 'B32'
                elif elType == 'tria6':
                    aElType = 'STRI65'
                elif elType == 'quad8':
                    aElType = 'S8'
                elif elType == 'penta15':
                    aElType = 'C3D15'
                elif elType == 'hexa20':
                    aElType = 'C3D20'
                elif elType == 'tetra10':
                    aElType = 'C3D10'
                else:
                    sys.stdout.write(
                        "\n **ERROR** writeAbaqus() : Element Type '%s' not implemented!\n\n" % repr(elType))
                    sys.stdout.flush()
                    sys.stdout.write('\n E N D E D  with ERRORS \n\n')
                    sys.stdout.flush()
                    exit(1)
                os.write('*ELEMENT, TYPE=%s, ELSET=%s\n' % (aElType, setName))
                for elId in elsets[setName]:
                    os.write('%s' % repr(elId))
                    count = 1
                    for node in elems[elId].get_nodes():
                        count += 1
                        if count == 8:
                            os.write(', %s,\n' % repr(node))
                            count = 0
                        elif count == 1:
                            os.write('%s' % repr(node))
                        else:
                            os.write(', %s' % repr(node))

                    if count != 0:
                        os.write('\n')

    else:
        os.write('** no ELEMENTS and ELSET written\n')
    os.close
    return

# Medtool class
class Node_Class:

    def __init__(self, id, x, y=None, z=None):
        self.id = id
        self.x = x
        self.y = y
        self.z = z
        self.elemList = []

    def get_coord(self):
        return (
            self.x, self.y, self.z)

    def get_coord_numpy(self):
        return np.array([self.x, self.y, self.z])

    def get_x(self):
        return self.x

    def get_y(self):
        return self.y

    def get_z(self):
        return self.z

    def get_id(self):
        return self.id

    def set_id(self, _id):
        self.id = _id

    def set_coord(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def set_coord_numpy(self, arr):
        self.x = arr[0]
        self.y = arr[1]
        self.z = arr[2]

    def set_x(self, x):
        self.x = x

    def set_y(self, y):
        self.y = y

    def set_z(self, z):
        self.z = z

    def append_to_elemList(self, elementID):
        self.elemList.append(elementID)

    def get_elemList(self):
        return self.elemList

    def get_dimension(self):
        if self.y == None:
            return 1
        else:
            if self.z == None:
                return 2
            return 3
            return

    def show(self):
        print('\nNODE Info:')
        print('id       =', self.id)
        print('x,y,z    =', self.x, self.y, self.z)
        print('elemList =', self.elemList)
class Element_Class:

    def __init__(self, id, nodes, type):
        self.id = id
        self.nodes = nodes
        self.type = type
        self.part = None
        self.mat = None
        self.elems = {}
        self.bbox = {}
        return

    def get_id(self):
        return self.id

    def set_id(self, _id):
        self.id = _id

    def get_type(self):
        return self.type

    def set_type(self, _type):
        self.type = _type

    def get_nodes(self):
        return self.nodes

    def set_nodes(self, nlist):
        self.nodes = nlist

    def append_node(self, node):
        self.nodes.append(node)

    def get_part(self):
        return self.part

    def set_part(self, _id):
        self.part = _id

    def get_mat(self):
        return self.mat

    def set_mat(self, _mat):
        self.mat = _mat

    def get_elems(self):
        return self.elems

    def set_elems(self, elDict):
        self.elems = elDict

    def show(self):
        print('\nELEMENT Info:')
        print('id     =', self.id)
        print('nodes  =', self.nodes)
        print('type   =', self.type)

    def get_center(self):
        x = 0.0
        y = 0.0
        z = 0.0
        for noid in self.nodes:
            x += self.nodes[noid].get_x()
            y += self.nodes[noid].get_y()
            z += self.nodes[noid].get_z()

        return (x, y, z)

#%%
# Preprocessing functions
def Resample(Image, Factor=None, Size=[None], Spacing=[None]):

    Dimension = Image.GetDimension()
    OriginalSpacing = np.array(Image.GetSpacing())
    OriginalSize = np.array(Image.GetSize())
    PhysicalSize = OriginalSize * OriginalSpacing

    Origin = Image.GetOrigin()
    Direction = Image.GetDirection()
    Center = OriginalSize * OriginalSpacing / 2

    if Factor:
        NewSize = [round(Size/Factor) for Size in Image.GetSize()] 
        NewSpacing = [PSize/(Size-1) for Size,PSize in zip(NewSize, PhysicalSize)]
    
    elif Size[0]:
        NewSize = Size
        NewSpacing = [PSize/(Size-1) for Size,PSize in zip(NewSize, PhysicalSize)]
    
    elif Spacing[0]:
        NewSpacing = Spacing
        NewSize = [round(Size/Spacing) + 1 for Size,Spacing in zip(PhysicalSize, NewSpacing)]
    
    NewArray = np.zeros(NewSize[::-1],'int')
    NewImage = sitk.GetImageFromArray(NewArray)
    NewImage.SetOrigin(Origin)
    NewImage.SetDirection(Direction)
    NewImage.SetSpacing(NewSpacing)
  
    Transform = sitk.TranslationTransform(Dimension)
    
    return sitk.Resample(Image, NewImage, Transform, sitk.sitkLinear, 0.0)
def GetTopAndBot(Image):

    """
    Return mean height of top and bottom surface
    """

    Array = sitk.GetArrayFromImage(Image).astype('bool')
    MidXSlice = Array[:,:,Array.shape[2] // 2]
    Sum = np.sum(MidXSlice, axis=0)
    Counts = np.bincount(Sum[Sum > 0])
    MeanSampleHeigth = np.argmax(Counts)
    MeanHeightPositions = np.where(Sum == MeanSampleHeigth)[0]

    TopNodes = []
    BotNodes = []
    for Position in MeanHeightPositions:
        Nodes = np.argwhere(MidXSlice[:,Position])
        TopNodes.append(Nodes.min())
        BotNodes.append(Nodes.max())

    MeanTop = int(np.mean(TopNodes).round(0))
    MeanBot = int(np.mean(BotNodes).round(0))
    
    return MeanTop, MeanBot
def CommonRegion(Bone, CommonFile, CommonFile_uCT):

    Mask = sitk.ReadImage(CommonFile)
    Array = sitk.GetArrayFromImage(Mask).transpose((2,1,0))

    Array_Adjusted = Adjust_Image_Size(Array, Bone['CoarseFactor'], CropZ='Crop')

    List = ['SEG', 'BMD', 'CORTMASK', 'TRABMASK']
    for iL, L in enumerate(List):
        Name = L + '_Array'
        Bone[Name] *= Array_Adjusted

    Bone['Common'] = Array_Adjusted

    Mask_uCT = sitk.ReadImage(CommonFile_uCT)

    # Resample uCT using nearest neighbour for same spacing
    Resampled_uCT = Resample(Mask_uCT, Spacing=Bone['Spacing'])

    Array_uCT = sitk.GetArrayFromImage(Resampled_uCT).transpose((2,1,0))
    Bone['Common_uCT'] = Adjust_Image_Size(Array_uCT, Bone['CoarseFactor'], CropZ='Crop')

    return Bone
def Calculate_BVTV(Bone, Config, ImageType):

    """
    Adapted from Denis's preprocessing_SA.py
    Calculate BVTV and mask images
    ------------------------------
    Scaling, slope and intercept are printed out for review
    If image is already in BMD units, Scaling, Slope and
    Intercept are not applied. BVTVraw is scaled according to
    Hosseini et al. 2017
    (This scaling function could as well be defined externally).

    Parameters
    ----------
    bone    bone results dictionary
    config  configuration parameters dictionary
    IMTYPE  string defining the type of image (BMD/NATIVE)

    Returns
    -------
    bone    bone results dictionary
    """

    # get bone values
    Scaling = Bone["Scaling"]
    Slope = Bone["Slope"]
    Intercept = Bone["Intercept"]
    BMD_Array = Bone["BMD_Array"]

    if Config['Echo'] == True:
        print("\n ... prepare mask and BVTV images")
        print("     -> Scaling   = ", Scaling)
        print("     -> Slope     = ", Slope)
        print("     -> Intercept = ", Intercept)

    if ImageType.find('BMD') > -1:
        # if image is already in BMD units (e.g. Hosseinis data)
        BVTV_Raw = BMD_Array / 1200.0
    elif ImageType.find('NATIVE') > -1:
        BMD_Array = (BMD_Array / Scaling) * Slope + Intercept
        BVTV_Raw = BMD_Array / 1200.0  # if image is in native units

    # Scaling of BVTV 61um to BVTV 11.4um [Hosseini2017]
    Seg_Scaling_Slope = 0.963
    Seg_Scaling_Intercept = 0.03814

    # BV/TV scaling Hosseini
    if Config['BVTV_Scaling'] == 1:
        BVTV_Scaled = Seg_Scaling_Slope * BVTV_Raw + Seg_Scaling_Intercept
    else:
        BVTV_Scaled = Config['BVTV_Slope'] * BVTV_Raw + Config['BVTV_Intercept']

    # Set bone values
    Mask = Bone['CORTMASK_Array'] + Bone['TRABMASK_Array']
    Mask[Mask > 0] = 1
    Bone['BVTV_Scaled'] = BVTV_Scaled * Mask
    Bone['BMD_Scaled'] = BVTV_Scaled * 1200 * Mask
    Bone['BVTV_Raw'] = BVTV_Raw * Mask

    return Bone
def Generate_Mesh(Bone, FileNames, Config):

    """
    Adapted from Denis's preprocessing_SA.py -> PSL_generate_full_block_mesh_accurate
    Creates Abaqus mesh from coarsened BVTV image and writes MESH to input file (.inp)
    Elements, nodes and element sets are read from the input file and stored in bone.
    Extended to add artificial layers at top and bottom of the image, for reducing
    influences of boundary conditions on homogeneity of strain measures.
    Debugged and checked for right orientations

    Parameters
    ----------
    bone
    config
    filenames

    Returns
    -------
    bone
    """

    # Get bone values

    BVTV_Scaled = Bone['BVTV_Scaled']
    CORTMASK_Array = Bone['CORTMASK_Array']
    TRABMASK_Array = Bone['TRABMASK_Array']
    FEelSize = Bone['FEelSize']
    Spacing = Bone['Spacing']
    CoarseFactor = Bone['CoarseFactor']

    BVTV_Masked = np.copy(BVTV_Scaled)
    MASK_Array = np.add(CORTMASK_Array, TRABMASK_Array)
    BVTV_Masked[MASK_Array == 0] = 0

    if Config['Registration']:
        MeshShape = Bone['Common_uCT'].shape
    else:
        MeshShape = BVTV_Scaled.shape

    # Adjust element size and coarse factor to fit image size
    if Config['Adjust_ElementSize']:

        if Config['Echo'] == True:
            print('\nAdjust elements size')
        Height = Spacing[2] * MeshShape[2]
        N_Elements = np.floor(Height / FEelSize[2]) + 1

        if Config['Echo'] == True:
            print('Original coarse factor: %.3f' % (CoarseFactor))
        CoarseFactor = np.floor(MeshShape[2] / N_Elements * 1E6) / 1E6

        if Config['Echo'] == True:
            print('New coarse factor: %.3f' % (CoarseFactor))

        FEelSize = Spacing * CoarseFactor
        if Config['Echo'] == True:
            print('Adjusted elements size: %.3f' % (FEelSize[2]))

        Bone['Spacing'] = Spacing 
        Bone['CoarseFactor'] = CoarseFactor 



    # Create array for MESH (no padding)
    MESH = np.ones(([int(dim) for dim in np.floor(np.array(MeshShape) / CoarseFactor)]))
    MESH = MESH.transpose(2, 1, 0)  # weird numpy array convention (z,y,x)

    if Config['Echo'] == True:
        Print_Memory_Usage()
        print('Spacing = ' + str(Spacing))
        print('FEelSize = ' + str(FEelSize))
        print(FEelSize[0] / 0.082)

    # Write MESH to Abaqus input file
    if Config['Echo'] == True:
        print('\n\nGenerate full block mesh (Abaqus inp file)')
    Input_FilneName = FileNames['INPname']

    WriteAbaqusGeneral(Input_FilneName, MESH, FEelSize)
    Input_Data = ReadAbaqus(Input_FilneName)
    # title = Input_Data[0]
    Nodes = Input_Data[1]
    # nsets = Input_Data[2]
    Elements = Input_Data[3]
    Elements_Sets = Input_Data[4]
    # element set "SET1" correspondes to the full block including padding layers

    # New element sets "BONE" and "GHOST" are created after material mapping
    Elements = {Element: Elements[Element] for Element in Elements_Sets["SET1"]}
    Nodes = {Node: Nodes[Node] for Element in Elements for Node in Elements[Element].get_nodes()}
    Elements_Sets = {}
    if Config['Echo'] == True:
        print('\nFinished')

    # Set Bone values
    Bone['Elements'] = Elements
    Bone['Nodes'] = Nodes
    Bone['Elements_Sets'] = Elements_Sets
    Bone['Mesh'] = MESH

    return Bone
def Isotropic_Fabric():
    """
    Returns isotropic fabric
    return [eval1, eval2, eval3], [evecxx, evecxy, evecxz], [evecyx, evecyy, evecyz], [eveczx, eveczy, eveczz]]
    """
    return [1.0, 1.0, 1.0], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
def Calculate_Iso_Fabric(Bone, Echo=False):

    """
    Adapted from Denis's preprocessing_SA.py
    Compute isotropic fabric
    """

    if Echo:
        print('\n\nCompute isotropic fabric')
    EigenValues, EigenVectors = Isotropic_Fabric()

    if Echo:
        print('\nFinished')

        Print_Memory_Usage()

    Bone['EigenValues'] = EigenValues
    Bone['EigenVectors'] = EigenVectors

    return Bone
def Numpy2VTK(NumpyArray, Spacing):
    """turns a numpy array into a vtk image data"""
    # vtk and numpy have different array conventions
    NumpyArray_Flat = NumpyArray.transpose(2, 1, 0).flatten()
    if NumpyArray.dtype == "int8":
        ArrayType = vtk.VTK_CHAR
    elif NumpyArray.dtype == "int16":
        ArrayType = vtk.VTK_SHORT
    else:
        ArrayType = vtk.VTK_FLOAT
    VTK_Image = numpy_to_vtk(num_array=NumpyArray_Flat, deep=True, array_type=ArrayType)
    Image = vtk.vtkImageData()
    Image.SetDimensions(NumpyArray.shape)
    Image.SetSpacing(Spacing)
    Points = Image.GetPointData()
    Points.SetScalars(VTK_Image)
    return Image

@njit
def TransformPoints(Points, C1, R1, T1, C2, R2, T2, C3, R3, T3):
    
    TransformedPoints = []
    
    for Point in Points:

        TP = np.dot(R1, Point + T1 - C1) + C1
        TP = np.dot(R2, TP + T2 - C2) + C2
        TP = np.dot(R3, TP + T3 - C3) + C3

        TransformedPoints.append(TP)

    return np.array(TransformedPoints)

def InverseTransformPoints(Points, C1, R1, T1, C2, R2, T2, C3, R3, T3):
    
    R1 = np.linalg.inv(R1)
    R2 = np.linalg.inv(R2)
    R3 = np.linalg.inv(R3)
    
    TransformedPoints = []
    
    for Point in Points:

        TP = np.dot(R3, Point - C3) + C3 - T3
        TP = np.dot(R2, TP - C2) + C2 - T2
        TP = np.dot(R1, TP - C1) + C1 - T1

        TransformedPoints.append(TP)

    return np.array(TransformedPoints)

@njit
def AssignVTKCells2Masks(NFacet, COG_Temp, TRAB_Mask, Spacing, Tolerance, DimZ):

    '''
    Function to run forloop in numba created by Michael Indermaur
    '''

    COGPoints_Cort = []
    COGPoints_Trab = []
    Indices_Cort = []
    Indices_Trab = []

    for i in NFacet:

        COGPoints_Temp = COG_Temp[i]
        
        # Compute array indices of cog to define in what bone phase it is located (trab or cort)         
        Mask_COG1 = (COGPoints_Temp[0] - (COGPoints_Temp[0] % Spacing[0])) / Spacing[0]
        Mask_COG2 = (COGPoints_Temp[1] - (COGPoints_Temp[1] % Spacing[1])) / Spacing[1]
        Mask_COG3 = (COGPoints_Temp[2] - (COGPoints_Temp[2] % Spacing[2])) / Spacing[2]
        
        Mask_COG = [Mask_COG1, Mask_COG2, Mask_COG3]

        # Check if cog of triangle is in trabecular mask
        if TRAB_Mask[int(Mask_COG[0])][int(Mask_COG[1])][int(Mask_COG[2])] > 0 and 0 + Tolerance <= COGPoints_Temp[2] <= DimZ - Tolerance:
            COGPoints_Trab.append(COGPoints_Temp)
            Indices_Trab.append(i)

        # Check if cog of triangle is in cortical mask
        # We only check if it was not in trabecular mask (would have been chatched before) and if its not in tolerance
        # If these two are true, it must be in cortical mask, or very close to the outer shell.
        elif 0 + Tolerance <= COGPoints_Temp[2] <= DimZ - Tolerance:
            COGPoints_Cort.append(COGPoints_Temp)
            Indices_Cort.append(i)

    return COGPoints_Trab , Indices_Trab , COGPoints_Cort , Indices_Cort
def Assign_MSL_Triangulation(Bone, SEG_array, Image_Dim, Tolerance, TRAB_Mask, Spacing, FileNames, Config):

    """
    Adapted from Denis's preprocessing_SA.py
    This function is used for evaluating MSL fabric tensors. Fabric tensors are returned in two sets:
    - cortical MSL: Return values for triangles with cog in cortical mask (add on: 'cort')
    - trabecular MSL: Return values for triangles with cog in trabecular mask (add on: 'trab')

    Return values are stored in bone: dict as follows:
    - ndizes = indices of triangles in specific phase
    - numberfacet = number of triangles in specific phase
    - cog_points = center of gravity of all triangles in specific phase
    - areadyadic = area weighted diadic product of spanning triangle vectors of specific phase

    Parameters
    ----------
    bone                results dictionary
    SEG_array           image array of segmentation [X, Y, Z]
    image_dimensions    dimensions of the image [x, Y, Z]
    tolerance           tolerance value for z-dimension
    trabmask            binary trabecular mask image [X, Y, Z]
    cortmask            binary cortical mask image [X, Y, Z]
    Spacing             image resolution [dX, dY, dZ]

    Returns
    -------

    """

    # Compute image dimensions
    DimX = Image_Dim[0]
    DimY = Image_Dim[1]
    DimZ = Image_Dim[2]

    # To use both phases in vtk triangulation, they mast all have value = 1
    SEG_array[SEG_array > 0] = 1
    SEG_VTK_Image = Numpy2VTK(SEG_array, Spacing)
    del SEG_array
    if Config['Echo'] == True:
        Print_Memory_Usage()

    # Create STL file from segmented image
    Time.Update((3 + 1/7)/10, 'Create STL')
    STL = vtk.vtkDiscreteMarchingCubes()
    STL.SetInputData(SEG_VTK_Image)
    del SEG_VTK_Image
    STL.GenerateValues(1, 1, 1)
    STL.Update()
    if Config['Echo'] == True:
        Print_Memory_Usage()

    # Decimate STL
    Time.Update((3 + 2/7)/10, 'Decimate cells')
    STLdeci = vtk.vtkDecimatePro()
    STLdeci.SetInputConnection(STL.GetOutputPort())
    STLdeci.SetTargetReduction(0.9)
    STLdeci.PreserveTopologyOn()
    STLdeci.Update()

    if Config['Echo'] == True:
        Print_Memory_Usage()

    del STL

    if Config['Echo'] == True:
        Print_Memory_Usage()

    # Calculate number of cells in triangulated mesh
    Time.Update((3 + 3/7)/10, 'Compute cell #')
    vtkSTL = STLdeci.GetOutput()
    NFacet = np.arange(vtkSTL.GetNumberOfCells())

    # Calculate center of gravity for each triangle (xc = (x1+x2+x3)/3...)
    # Only keep cogs which are not at the border (z-direction)
    a = dsa.WrapDataObject(vtkSTL)

    # Optimized to run with numba added by Michael Indermaur
    # Find Center of gravity of each cell
    Time.Update((3 + 4/7)/10, 'Compute COGs')
    Filt = vtk.vtkCellCenters()
    Filt.SetInputDataObject(vtkSTL)
    Filt.Update()
    COG_Temp = dsa.WrapDataObject(Filt.GetOutput()).Points

    COGPoints_Trab, Indices_Trab, COGPoints_Cort, Indices_Cort = AssignVTKCells2Masks(np.array(NFacet), np.array(COG_Temp), np.array(TRAB_Mask), np.array(Spacing), np.array(Tolerance), np.array(DimZ))
    
    # Transform COG points
    if Config['Registration']:
        I = sitk.ReadImage(FileNames['Common'])
        Center = np.array(I.GetSize()) / 2 * np.array(I.GetSpacing())
        C1 = Center + np.array(I.GetOrigin())
        R1 = np.array([[-1, 0, 0],[0, 1, 0],[0, 0, -1]])
        T1 = np.array([0, 0, 0])

        IT = sitk.ReadTransform(FileNames['InitialTransform'])
        C2 = np.array(IT.GetFixedParameters()[:-1], 'float')
        P2 = IT.GetParameters()
        R2 = RotationMatrix(-P2[0], -P2[1], -P2[2])
        T2 = -np.array(P2[3:])

        FT = GetParameterMap(FileNames['Transform'])
        C3 = np.array(FT['CenterOfRotationPoint'], 'float')
        P3 = np.array(FT['TransformParameters'],'float')
        R3 = RotationMatrix(-P3[0], -P3[1], -P3[2])
        T3 = -np.array(P3[3:])

        COGPoints_Trab = TransformPoints(np.array(COGPoints_Trab), C1, R1, T1, C2, R2, T2, C3, R3, T3)
        COGPoints_Cort = TransformPoints(np.array(COGPoints_Cort), C1, R1, T1, C2, R2, T2, C3, R3, T3)

    # Compute cell normals and dyadic product
    vtkNormals = vtk.vtkPolyDataNormals()
    vtkNormals.SetInputConnection(STLdeci.GetOutputPort())

    del STLdeci
    if Config['Echo'] == True:
        Print_Memory_Usage()

    vtkNormals.ComputeCellNormalsOn()
    vtkNormals.ComputePointNormalsOff()
    vtkNormals.ConsistencyOn()
    vtkNormals.AutoOrientNormalsOn()  # Only works with closed surface. All Normals will point outward.
    vtkNormals.Update()
    PointNormalArray = vtkNormals.GetOutput().GetCellData().GetNormals()

    Time.Update((3 + 5/7)/10, 'Compute dyadics')
    Dyad_Cort = np.zeros([3, 3])
    Dyad_Trab = np.zeros([3, 3])
    Dyadic_Cort = []
    Dyadic_Trab = []

    for i in Indices_Cort:
        vtk.vtkMath.Outer(PointNormalArray.GetTuple(i), PointNormalArray.GetTuple(i), Dyad_Cort)
        Dyadic_Cort.append(Dyad_Cort.tolist())

    for i in Indices_Trab:
        vtk.vtkMath.Outer(PointNormalArray.GetTuple(i), PointNormalArray.GetTuple(i), Dyad_Trab)
        Dyadic_Trab.append(Dyad_Trab.tolist())

    # Get Cell Area https://www.vtk.org/Wiki/VTK/Examples/Python/MeshLabelImage
    TriangleCellAN = vtk.vtkMeshQuality()
    TriangleCellAN.SetInputConnection(vtkNormals.GetOutputPort())
    TriangleCellAN.SetTriangleQualityMeasureToArea()
    TriangleCellAN.SaveCellQualityOn()  # default
    TriangleCellAN.Update()  # creates vtkDataSet
    QualityArray = TriangleCellAN.GetOutput().GetCellData().GetArray("Quality")

    Time.Update((3 + 6/7)/10, 'Compute areas')
    Area_Cort = []
    Area_Trab = []

    for i in Indices_Cort:
        Area_Cort.append(QualityArray.GetValue(i))

    for i in Indices_Trab:
        Area_Trab.append(QualityArray.GetValue(i))

    # area dyadic represents the multiplication of the area with the cross-product of the normals of each triangle
    # these values can now be assigned to the elements according to the center of gravity of the triangle
    # all lists are sorted according to index (position in list is index identifier for triangles)
    AreaDyadic_Cort = [np.multiply(a, b) for a, b in zip(Area_Cort, Dyadic_Cort)]
    AreaDyadic_Trab = [np.multiply(a, b) for a, b in zip(Area_Trab, Dyadic_Trab)]

    if Config['Echo'] == True:
        Print_Memory_Usage()

    Bone['CogPoints_Cort'] = COGPoints_Cort
    Bone['CogPoints_Trab'] = COGPoints_Trab
    Bone['AreaDyadic_Cort'] = AreaDyadic_Cort
    Bone['AreaDyadic_Trab'] = AreaDyadic_Trab
    Bone['NFacet'] = NFacet
    Bone['Indices_Cort'] = Indices_Cort
    Bone['Indices_Trab'] = Indices_Trab

    return Bone

@njit
def Mapping_Isosurface(Indices, CogPoints, FEelSize, FEDimX, FEDimY, FEDimZ, AreaDyadic, MSL_Values):
    '''
    Function to run forloop in numba created by Michael Indermaur
    '''

    for i, value in enumerate(Indices):
        # This block returns the position of the element by calculating cog modulo FEelsize
        xn = (CogPoints[i][0] - (CogPoints[i][0]-np.floor(CogPoints[i][0]/FEelSize[0])*FEelSize[0])) / FEelSize[0]  # Element position number in X
        yn = (CogPoints[i][1] - (CogPoints[i][1]-np.floor(CogPoints[i][1]/FEelSize[1])*FEelSize[1])) / FEelSize[1]  # Element position number in Y
        zn = (CogPoints[i][2] - (CogPoints[i][2]-np.floor(CogPoints[i][2]/FEelSize[2])*FEelSize[2])) / FEelSize[2]  # Element position number in Z

        # in case a cog_point is directly on the max border, 1 needs to be subtracted from position
        # Happens most often at the z borders.
        if xn == FEDimX:
            xn = xn - 1
        if yn == FEDimY:
            yn = yn - 1
        if zn == FEDimZ:
            zn = zn - 1

        # Compute element number out of element position numbers xyz
        elnum = int((xn + 1) + ((yn) * FEDimX) + ((zn) * FEDimX * FEDimY))  # smallest element number is 1, not 0 (xn+1)
        if elnum<np.shape(MSL_Values)[0]:
            MSL_Values[elnum] += AreaDyadic[i]
        else:
            print('Index elnum not available:   ' + str(elnum))
            pass
    
    return MSL_Values
def Compute_Local_MSL(Bone, Config, FileNames):

    """
    Adapted from Denis's preprocessing_SA.py
    Compute local MSL
    """

    # Read Config dict
    STL_Tolerance = Config['STL_Tolerance']
    ROI_Kernel_Size_Cort = Config['ROI_Kernel_Size_Cort']
    ROI_Kernel_Size_Trab = Config['ROI_Kernel_Size_Trab']

    # Read Bone dict
    Spacing = Bone['Spacing']
    SEG_array = Bone['SEG_Array']
    TRAB_Mask = Bone['TRABMASK_Array']
    CORT_Mask = Bone['CORTMASK_Array']
    MESH = Bone['Mesh']
    FEelSize = Bone['FEelSize']

    Image_Dim = np.shape(SEG_array) * Spacing

    # Compute STL elements, their normal and area (AreaDyadic)
    Bone = Assign_MSL_Triangulation(Bone, SEG_array, Image_Dim, STL_Tolerance, TRAB_Mask, Spacing, FileNames, Config)

    # General variables for both compartments
    # Find dimensions of mesh
    FEDimX = MESH.shape[2]  # Dimension in X
    FEDimY = MESH.shape[1]  # Dimension in Y
    FEDimZ = MESH.shape[0]  # Dimension in Z
    NFacet = Bone['NFacet']

    # Cortical compartment
    Indices_Cort = List() # modified to silent numba depreciation warning
    [Indices_Cort.append(i) for i in Bone['Indices_Cort']]
    CogPoints_Cort = List() # modified to silent numba depreciation warning
    [CogPoints_Cort.append(i) for i in Bone['CogPoints_Cort']]
    AreaDyadic_Cort = List() # modified to silent numba depreciation warning
    [AreaDyadic_Cort.append(i) for i in Bone['AreaDyadic_Cort']]


    # array has length FEDimX*FEDimX*FEDimZ + 1, so that index i corresponds to element number, starting from 1
    # Create empty list for AreaDyadic values
    MSL_Values_Cort = np.zeros((FEDimX * FEDimY * FEDimZ + 1, 3, 3))

    # Assign AreaDyadic values to cortical elements
    # Each AreaDyadic value of a triangle is added to the pool of FE element it's lying in
    MSL_Values_Cort = Mapping_Isosurface(Indices_Cort, CogPoints_Cort, FEelSize, FEDimX, FEDimY, FEDimZ, AreaDyadic_Cort, MSL_Values_Cort)

    # Reshape MSL_Values in 3D structure
    Dim_MSL_Cort = MSL_Values_Cort.shape[0]
    MSL_Cort = np.reshape(MSL_Values_Cort[1:], [FEDimZ, FEDimY, FEDimX, 3, 3])

    # Apply Kernel to smooth fabric
    Kernel_Cort = np.ones([ROI_Kernel_Size_Cort, ROI_Kernel_Size_Cort, ROI_Kernel_Size_Cort])
    Kernel_Cort = Kernel_Cort[:, :, :, None, None]
    # Filter MSL image with Kernel
    MSL_Kernel_Cort = scipy.ndimage.convolve(MSL_Cort, Kernel_Cort, mode='constant', cval=0.0)
    # Reshape MSL_kernel_array to list
    MSL_Kernel_List_Cort = np.reshape(MSL_Kernel_Cort, [Dim_MSL_Cort - 1, 3, 3])

    Bone['MSL_Kernel_List_Cort'] = MSL_Kernel_List_Cort


    # Trabecular compartment
    Indices_Trab = List()
    [Indices_Trab.append(i) for i in Bone['Indices_Trab']]
    CogPoints_Trab = List()
    [CogPoints_Trab.append(i) for i in Bone['CogPoints_Trab']]
    AreaDyadic_Trab = List()
    [AreaDyadic_Trab.append(i) for i in Bone['AreaDyadic_Trab']]

    # array has length FEDimX*FEDimY*FEDimZ + 1, so that index i corresponds to element number, starting from 1
    # Create empty list for areadyadic values
    MSL_Values_Trab = np.zeros((FEDimX * FEDimY * FEDimZ + 1, 3, 3))

    # Assign areadyadic values to trabecular elements
    # Each areadyadic value of a triangle is added to the pool of FE element it's lying in
    MSL_Values_Trab = Mapping_Isosurface(Indices_Trab, CogPoints_Trab, FEelSize, FEDimX, FEDimY, FEDimZ, AreaDyadic_Trab, MSL_Values_Trab)

    # Convert MSL_values to numpy array and reshape in 3D structure
    # ----------------------------------------------------------------
    Dim_MSL_trab = MSL_Values_Trab.shape[0]
    MSL_Trab = np.reshape(MSL_Values_Trab[1:], [FEDimZ, FEDimY, FEDimX, 3, 3])

    # Apply Kernel to smooth fabric
    Kernel_Trab = np.ones([ROI_Kernel_Size_Trab, ROI_Kernel_Size_Trab, ROI_Kernel_Size_Trab])
    Kernel_Trab = Kernel_Trab[:, :, :, None, None]
    # Filter MSL image with Kernel
    MSL_Kernel_Trab = scipy.ndimage.convolve(MSL_Trab, Kernel_Trab, mode='constant', cval=0.0)
    # Reshape MSL_kernel_array to list
    MSL_Kernel_List_Trab = np.reshape(MSL_Kernel_Trab, [Dim_MSL_trab - 1, 3, 3])

    Bone['MSL_Kernel_List_Trab'] = MSL_Kernel_List_Trab

    return Bone
def Compute_Phi(COG, Spacing, ROI_Size, Image_Array):

    """
    Computes bone partial volume from a numpy array containing
    the MASK values for a region of size 'ROIsize' centered in
    the center of gravity of the element
    """

    x, y, z = COG / Spacing
    ROI_Size = ROI_Size / Spacing[0]
    X = [max(x - ROI_Size / 2, 0), min(x + ROI_Size / 2, Image_Array.shape[0])]
    Y = [max(y - ROI_Size / 2, 0), min(y + ROI_Size / 2, Image_Array.shape[1])]
    Z = [max(z - ROI_Size / 2, 0), min(z + ROI_Size / 2, Image_Array.shape[2])]

    ROI = Image_Array[
          int(np.rint(X[0])): int(np.rint(X[1])),
          int(np.rint(Y[0])): int(np.rint(Y[1])),
          int(np.rint(Z[0])): int(np.rint(Z[1])),
          ]
    try:
        Phi = float(np.count_nonzero(ROI)) / ROI.size
    except:
        Phi = 0

    # check for meaningful output
    if np.isnan(Phi):
        Phi = 0.0
    if Phi > 1:
        Phi = 1
        print('\nPhi bigger than 1!\n')
    return Phi, X, Y, Z
def Sphere_Array(Shape, Radius, Position):
    Semi_Sizes = (float(Radius),) * 3
    grid = [slice(-x0, dim - x0) for x0, dim in zip(Position, Shape)]
    position = np.ogrid[grid]
    Array = np.zeros(np.asarray(Shape).astype(int), dtype=float)
    for x_i, Semi_Sizes in zip(position, Semi_Sizes):
        Array += np.abs(x_i / Semi_Sizes) ** 2
    return (Array <= 1.0).astype("int")
def Compute_BVTV_TwoPhases(COG, Spacing, ROI_Size_Cort_mm, ROI_Size_Trab_mm, Image_Array, Cort_Mask, Trab_Mask, Phi_Cort, Phi_Trab):
    """
    computes BVTV from a numpy array containing the BVTV values for a region of size 'ROI_Size' centered in the
    center of gravity of the element
    """

    # ROI size: If Phi_Trab = 0, ROI size = sphere with equal volume as FE element
    #           If Phi_Trab =! 0, ROI size = ROI_Size_mm

    # Set initial values for BVTV trab and cort
    Cort_Mean_BVTV = 0.0
    Trab_Mean_BVTV = 0.0

    # Cut out ROI from image array
    x, y, z = COG / Spacing

    ROI_Size_Trab = ROI_Size_Trab_mm / Spacing[0]
    ROI_Size_Cort = ROI_Size_Cort_mm / Spacing[0]

    X = [max(x - ROI_Size_Trab / 2, 0), min(x + ROI_Size_Trab / 2, Image_Array.shape[0])]
    Y = [max(y - ROI_Size_Trab / 2, 0), min(y + ROI_Size_Trab / 2, Image_Array.shape[1])]
    Z = [max(z - ROI_Size_Trab / 2, 0), min(z + ROI_Size_Trab / 2, Image_Array.shape[2])]

    ROI = Image_Array[
          int(np.rint(X[0])): int(np.rint(X[1])),
          int(np.rint(Y[0])): int(np.rint(Y[1])),
          int(np.rint(Z[0])): int(np.rint(Z[1])),
          ]

    ROI_Cort_Mask = Cort_Mask[
                    int(np.rint(X[0])): int(np.rint(X[1])),
                    int(np.rint(Y[0])): int(np.rint(Y[1])),
                    int(np.rint(Z[0])): int(np.rint(Z[1])),
                    ]
    ROI_Cort_Mask[ROI_Cort_Mask > 0] = 1

    ROI_Trab_Mask = Trab_Mask[
                    int(np.rint(X[0])): int(np.rint(X[1])),
                    int(np.rint(Y[0])): int(np.rint(Y[1])),
                    int(np.rint(Z[0])): int(np.rint(Z[1])),
                    ]
    ROI_Trab_Mask[ROI_Trab_Mask > 0] = 1

    # calculate center of sphere in new image
    xc = x - X[0]
    yc = y - Y[0]
    zc = z - Z[0]

    if Phi_Trab > 0.0:
        # Compute trabecular BVTV
        # ------------------------
        # create masking array
        ROI_Trab_Mask_Sphere = Sphere_Array(np.shape(ROI), ROI_Size_Trab / 2, [xc, yc, zc])
        # Read out mean BVTV of image with two/three masks
        Image_Trab_BVTV = ROI[ROI_Trab_Mask_Sphere + ROI_Trab_Mask == 2]

        Trab_Mean_BVTV = np.mean(Image_Trab_BVTV)

        # check for meaningful output
        if np.isnan(Trab_Mean_BVTV):
            Trab_Mean_BVTV = 0.0
        if Trab_Mean_BVTV > 1:
            Trab_Mean_BVTV = 1

    if Phi_Cort > 0.0:
        # Compute cortical BVTV
        # ------------------------
        # create sphere mask array cort
        ROI_Cort_Mask_Sphere = Sphere_Array(np.shape(ROI), ROI_Size_Cort / 2, [xc, yc, zc])
        # Read out mean BVTV of image with two masks
        Image_Cort_BVTV = ROI[ROI_Cort_Mask_Sphere + ROI_Cort_Mask == 2]
        # compute mean_BVTV_cort
        Cort_Mean_BVTV = np.mean(Image_Cort_BVTV)

        # check for meaningfull output
        if np.isnan(Cort_Mean_BVTV):
            Cort_Mean_BVTV = 0.0
        if Cort_Mean_BVTV > 1:
            Cort_Mean_BVTV = 1

    return Cort_Mean_BVTV, Trab_Mean_BVTV
def Compute_BVTV_FEel(COG, Spacing, FE_elSize_mm, Image_Array, Mask_Array):

    """
    Computes BVTV from a numpy array containing the BVTV values for a region
    of size 'ROI_Size' centered in the center of gravity of the element
    """

    # Cut out ROI from image array
    x, y, z = COG / Spacing
    FE_elSize = FE_elSize_mm[0] / Spacing[0]

    X = [max(x - FE_elSize / 2, 0), min(x + FE_elSize / 2, Image_Array.shape[0])]
    Y = [max(y - FE_elSize / 2, 0), min(y + FE_elSize / 2, Image_Array.shape[1])]
    Z = [max(z - FE_elSize / 2, 0), min(z + FE_elSize / 2, Image_Array.shape[2])]

    ROI = Image_Array[
          int(np.rint(X[0])): int(np.rint(X[1])),
          int(np.rint(Y[0])): int(np.rint(Y[1])),
          int(np.rint(Z[0])): int(np.rint(Z[1])),
          ]

    # The ROI for BVTV computation corresponds to the homogenized element
    ROI_Mask = Mask_Array[
               int(np.rint(X[0])): int(np.rint(X[1])),
               int(np.rint(Y[0])): int(np.rint(Y[1])),
               int(np.rint(Z[0])): int(np.rint(Z[1])),
               ]

    BVTV_FE = np.mean(ROI[ROI_Mask != 0])

    if np.isnan(BVTV_FE):
        BVTV_FE = 0.0

    return BVTV_FE
def PSL_Material_Mapping_Copy_Layers_Iso_Cort(Bone, Config, FileNames):
    """
    Adapted from Denis's preprocessing_SA.py -> PSL_material_mapping_copy_layers_accurate_iso_cort
    Material Mapping, including PSL ghost padding layers as copy of most distal and proximal layers
    For accurate PSL pipeline
    Additionaly, the optional BMC conversion can be specified in config.yaml. This function will conserve BMC from
    image to hFE model to ensure, no mass conservation.
    Debuged and checked for right orientations!

    Fabric computation:
    Cortical bone is assigned an isotropic fabric, trabecular bone is evaluated from MSL triangulation. For mixed
    phase elements, fabric is only evaluated for trabecular compartment. In UMAT, superposition is then done
    based on both phases. Isotropic fabric doesn't need to be rotated to have same coordinate system as trabecular
    one for superposition, because of isotropy.

    Parameters
    ----------
    Bone
    Config
    umat_parameters
    filenames

    Returns
    -------

    """

    # Get images
    BVTV_Scaled = Bone['BVTV_Scaled']
    BMD_array = Bone['BMD_Scaled']
    CORTMASK_Array = Bone["CORTMASK_Array"]
    TRABMASK_Array = Bone["TRABMASK_Array"]
    SEG_array = Bone["SEG_array"]
    # Create images for material mapping
    BVTV_Cort = np.copy(BVTV_Scaled)
    BVTV_Cort[CORTMASK_Array == 0] = 0
    BVTV_Trab = np.copy(BVTV_Scaled)
    BVTV_Trab[TRABMASK_Array == 0] = 0
    SEG_array[SEG_array > 0] = 1
    SEG_Cort_Masked = np.copy(SEG_array)
    SEG_Cort_Masked[CORTMASK_Array == 0] = 0
    SEG_Trab_Masked = np.copy(SEG_array)
    SEG_Trab_Masked[TRABMASK_Array == 0] = 0

    # Get Bone values
    FEelSize = Bone['FEelSize']
    Spacing = Bone['Spacing']
    Elements = Bone['Elements']
    Nodes = Bone['Nodes']
    Elements_Sets = Bone['Elements_Sets']
    ROI_BVTV_Size_Trab = Config['ROI_BVTV_Size_Trab']
    ROI_BVTV_Size_Cort = Config['ROI_BVTV_Size_Cort']

    # Local fabric type: Computed by compute_local_MSL and assign_MSL_triangulation
    MSL_Kernel_List = Bone['MSL_Kernel_List']

    # Material mapping procedure
    Elements_Sets['BONE'] = []
    Isotropic = 0
    SEG_Tot_Masked = SEG_Cort_Masked + SEG_Trab_Masked

    # local fabric is evaluated in cort and trab at the moment!
    Rhos_Cort = {}
    RHOc_corrected = {}  # RHO corrected by PBV (RHO * PHI)
    Rhos_Trab = {}
    RHOt_corrected = {}  # RHO corrected by PBV (RHO * PHI)
    Rhos_Cort_FE = {}    # RHO of only FE element (ROI = FEelement)
    Rhos_Trab_FE = {}    # RHO of only FE element (ROI = FEelement)
    Phis_Cort = {}
    Phis_Trab = {}
    mm = {}
    m = {}
    BVTVcortseg = {}
    BVTVtrabseg = {}
    BVTVcortseg_elem = {}
    BVTVtrabseg_elem = {}
    DOA = {}
    COGs = {}

    n_ortho = 0

    # Read boundary condition variables
    BCs_FileName = Config['BCs']
    # ---------------------------------------------------------------------------
    for i, Element in enumerate(Elements):

        # Compute center of gravity
        COG = np.nanmean([np.asarray(Nodes[Node].get_coord()) for Node in Elements[Element].get_nodes()],
                           axis=0)  # center of gravity of each element

        # Compute PHI from masks
        Phi_Cort, Xc, Yc, Zc = Compute_Phi(COG, Spacing, FEelSize[0], CORTMASK_Array)
        Phi_Trab, Xt, Yt, Zt = Compute_Phi(COG, Spacing, FEelSize[0], TRABMASK_Array)

        # If an element holds a part of a mask
        if Phi_Cort > 0.0 or Phi_Trab > 0.0:

            # 2.3 Compute BVTV
            Rho_Cort, Rho_Trab = Compute_BVTV_TwoPhases(COG, Spacing, ROI_BVTV_Size_Cort, ROI_BVTV_Size_Trab, BVTV_Scaled, CORTMASK_Array, TRABMASK_Array, Phi_Cort, Phi_Trab)

            Rho_Cort_FE = Compute_BVTV_FEel(COG, Spacing, FEelSize, BVTV_Scaled, CORTMASK_Array)
            Rho_Trab_FE = Compute_BVTV_FEel(COG, Spacing, FEelSize, BVTV_Scaled, TRABMASK_Array)

            # if option is true in config, correct FE mesh to not have any holes. Minimum BVTV is 1% for both phases
            if Config['All_Mask']:
                if Phi_Cort > 0.0 and Rho_Cort < 0.01:
                    Rho_Cort = 0.01
                if Phi_Trab > 0.0 and Rho_Trab < 0.01:
                    Rho_Trab = 0.01

            # Check if element holds bone or if mask is empty
            if Rho_Cort * Phi_Cort or Rho_Trab * Phi_Trab > 0.0:
                Elements_Sets['BONE'].append(Element)

                Phis_Cort[Element] = Phi_Cort
                Phis_Trab[Element] = Phi_Trab
                Rhos_Cort[Element] = Rho_Cort
                Rhos_Trab[Element] = Rho_Trab
                Rhos_Cort_FE[Element] = Rho_Cort_FE
                Rhos_Trab_FE[Element] = Rho_Trab_FE

                # Assign computed values to element
                RHOc_corrected[Element] = Rhos_Cort[Element] * Rhos_Cort[Element]
                RHOt_corrected[Element] = Rhos_Cort[Element] * Phis_Trab[Element]

                # Compute elemental BVTV from segmentation
                # Method computePHI can be used on segmentation instead of mask
                BVTVcortseg_elem[Element], Xcs, Ycs, Zcs = Compute_Phi(COG, Spacing, ROI_BVTV_Size_Cort, SEG_Cort_Masked)
                BVTVtrabseg_elem[Element], Xcs, Ycs, Zcs = Compute_Phi(COG, Spacing, ROI_BVTV_Size_Trab, SEG_Trab_Masked)
                try:
                    BVTVcortseg[Element] = BVTVcortseg_elem[Element] / Phis_Cort[Element]
                except:
                    BVTVcortseg[Element] = 0
                try:
                    BVTVtrabseg[Element] = BVTVtrabseg_elem[Element] / Phis_Trab[Element]
                except:
                    BVTVtrabseg[Element] = 0

                BVcortseg = BVTVcortseg_elem[Element] * FEelSize[0] ** 3
                BVtrabseg = BVTVtrabseg_elem[Element] * FEelSize[0] ** 3
                # Evaluate Fabric using MSL
                # ----------------------------------------------------------------
                try:
                    # MSL method according to Hosseini Bone 2017
                    H = 2 * (BVcortseg + BVtrabseg) * scipy.linalg.inv(MSL_Kernel_List[Element - 1])
                    MSL = 3 * H / np.trace(H)
                    EigenValues, EigenVectors = scipy.linalg.eig(MSL)

                    # order eigenvalues 0=min, 1=mid, 2=max
                    idx = EigenValues.argsort()
                    EigenValues = EigenValues[idx]
                    EigenVectors = EigenVectors[:, idx]
                    EigenValues = [e.real for e in EigenValues]
                    EigenVectors = [EigenVectors[:, p] for p in [0, 1, 2]]

                except:
                    Isotropic = Isotropic + 1
                    EigenValues, EigenVectors = Isotropic_Fabric()

                m[Element], mm[Element] = EigenValues, EigenVectors

                if np.dot(EigenVectors[:, 0], EigenVectors[:, 1]) != 0.0 or \
                        np.dot(EigenVectors[:, 0], EigenVectors[:, 2]) != 0.0 or \
                        np.dot(EigenVectors[:, 1], EigenVectors[:, 2]) != 0.0:
                    print('first two Eigenvectors are not orthogonal! Incidence  + ' + str(n_ortho))
                    n_ortho = n_ortho + 1

                DOA[Element] = EigenValues[0] / EigenValues[2]
                COGs[Element] = COG

        Time.Update((4 + i/(len(Elements) - 1)*4)/10, 'Material mapping')

    # conversion to np array for calculation of BVTV and selection of only elements contained in ELSET BONE
    # -----------------------------------------------------------------------------------------------------
    # these arrays are only used for computations in the summary file, and not for the abaqus input file.
    # Therefore, only elements belonging to ELSET BONE are considered.

    # Cortical bone
    PHIc_array = np.array([Phis_Cort[k] for k in Elements_Sets['BONE'] if k in Phis_Cort])
    RHOc_orig_array = np.array([Rhos_Cort[k] for k in Elements_Sets['BONE'] if k in Rhos_Cort])
    RHOc_FE_array = np.array([Rhos_Cort_FE[k] for k in Elements_Sets['BONE'] if k in Rhos_Cort_FE])

    # Trabecular bone
    PHIt_array = np.array([Phis_Trab[k] for k in Elements_Sets['BONE'] if k in Phis_Trab])
    RHOt_orig_array = np.array([Rhos_Trab[k] for k in Elements_Sets['BONE'] if k in Rhos_Trab])
    RHOt_FE_array = np.array([Rhos_Trab_FE[k] for k in Elements_Sets['BONE'] if k in Rhos_Trab_FE])

    cogs_array = np.array([COGs[k] for k in Elements_Sets['BONE'] if k in COGs])
    DOA_array = np.array(DOA.values())

    # -----------------------------------------------------------------------------------------------------

    # Create elements and nodes for Abaqus Input File
    Elements = {Element: Elements[Element] for Element in Elements_Sets['BONE']}
    Bone_Elements = Elements


    # BMC compensation for all BVTV values in order to conserve bone mass during homogenization
    # -----------------------------------------------------------------------------------------------------
    BMC_reco_c = np.sum(BMD_array[CORTMASK_Array > 0]) * Spacing[0] ** 3 / 1000
    BMC_sim_c = np.sum(RHOc_orig_array * PHIc_array * FEelSize[0] ** 3) * 1200 / 1000
    lambda_BMC_c = BMC_reco_c / BMC_sim_c

    BMC_reco_t = np.sum(BMD_array[TRABMASK_Array > 0]) * Spacing[0] ** 3 / 1000
    BMC_sim_t = np.sum(RHOt_orig_array * PHIt_array * FEelSize[0] ** 3) * 1200 / 1000
    lambda_BMC_t = BMC_reco_t / BMC_sim_t

    # 2) Copy RHOc and RHOt dict to save uncompensated BVTV values
    RHOc_original = copy.deepcopy(Rhos_Cort)  # use deepcopy to avoid shallow copy
    RHOt_original = copy.deepcopy(Rhos_Trab)

    # 3) Compensate RHOb BVTV values
    for Element in Bone_Elements:
        # Cortical BVTV
        if Rhos_Cort[Element] * lambda_BMC_c < 1.0:
            Rhos_Cort[Element] = RHOc_original[Element] * lambda_BMC_c
        else:
            Rhos_Cort[Element] = 1.0

    for Element in Bone_Elements:
        # Trabecular BVTV
        if Rhos_Trab[Element] * lambda_BMC_t < 1.0:
            Rhos_Trab[Element] = RHOt_original[Element] * lambda_BMC_t
        else:
            Rhos_Trab[Element] = 1.0

    RHOc_array = np.array([Rhos_Cort[k] for k in Elements_Sets['BONE'] if k in Rhos_Cort])
    RHOt_array = np.array([Rhos_Trab[k] for k in Elements_Sets['BONE'] if k in Rhos_Trab])

    Nodes = {Node: Nodes[Node] for Element in Elements for Node in Elements[Element].get_nodes()}

    # Write mesh to Abaqus input file
    INPname = FileNames['INPname']
    WriteAbaqus(INPname, None, Nodes, None, Elements, Elements_Sets, NscaResults=None)
    # *****************************************************************
    marray = np.real(np.mean([np.asarray(m[Element]) for Element in m.keys()], axis=0))
    mmarray1 = np.real(np.mean([np.asarray(mm[Element][0]) for Element in m.keys()], axis=0))
    mmarray2 = np.real(np.mean([np.asarray(mm[Element][1]) for Element in m.keys()], axis=0))
    mmarray3 = np.real(np.mean([np.asarray(mm[Element][2]) for Element in m.keys()], axis=0))

    if Config['Echo'] == True:
        Print_Memory_Usage()

    # store variables to bone dict
    Bone["RHOc_array"] = RHOc_array
    Bone["RHOt_array"] = RHOt_array
    Bone["RHOc_orig_array"] = RHOc_orig_array
    Bone["RHOt_orig_array"] = RHOt_orig_array
    Bone["PHIc_array"] = PHIc_array
    Bone["PHIt_array"] = PHIt_array
    Bone["RHOc_FE_array"] = RHOc_FE_array
    Bone["RHOt_FE_array"] = RHOt_FE_array
    Bone["Elements"] = Elements
    Bone["Bone_Elements"] = Bone_Elements
    Bone["Nodes"] = Nodes
    Bone["Elements_Sets"] = Elements_Sets
    Bone["marray"] = marray
    Bone["mmarray1"] = mmarray1
    Bone["mmarray2"] = mmarray2
    Bone["mmarray3"] = mmarray3
    Bone["cogs"] = cogs_array
    Bone["CoarseFactor"] = Bone["FEelSize"][0] / Bone["Spacing"][0]
    Bone["DOA"] = DOA_array
    Bone['m_dict'] = m
    Bone['mm_dict'] = mm
    Bone['COGs'] = COGs

    # Write elements and material properties to input file
    Time.Update(9/10, 'Update input file')
    outfile = open(INPname, 'a')
    outfile.write("***********************************************************\n")

    # Write node sets as elements with material properties
    for Element in Elements:
        outfile.write("*ELEMENT, TYPE=C3D8, ELSET=Elset" + str(Element) + "\n")
        outfile.write(str(Element) + ", " + str(Elements[Element].get_nodes()).replace("[", "").replace("]", "") + "\n")
        outfile.write("**POSITION: X = " + str(COGs[Element][0]) + " Y = " + str(COGs[Element][1]) + " Z = " + str(
            COGs[Element][2]) + "\n")
        outfile.write("*ORIENTATION, NAME=Orient" + str(Element) + "\n")
        outfile.write(
            str(mm[Element][0][0]) + ", " + str(mm[Element][0][1]) + ", " + str(mm[Element][0][2]) + ", " + str(mm[Element][1][0])
            + ", " + str(mm[Element][1][1]) + ", " + str(mm[Element][1][2]) + "\n")
        outfile.write("1, 0.\n")
        outfile.write("*SOLID SECTION, ELSET=Elset" + str(Element) + ",  MATERIAL=Mat" + str(Element) + ", ORIENTATION=Orient"
                      + str(Element) + "\n")
        outfile.write("*MATERIAL, NAME=Mat" + str(Element) + "\n")
        outfile.write("*USER MATERIAL, CONSTANTS=7, UNSYMM, TYPE=MECHANICAL\n")
        outfile.write("**BVTVcort, BVTVtrab, BPVcort, BPVtrab, eigenvalue min, eigenvalue mid, eigenvalue max\n")
        outfile.write(
            str(np.round(Rhos_Cort[Element], 5)) + ", " + str(np.round(Rhos_Trab[Element], 5)) + ", " + str(
                np.round(Phis_Cort[Element], 5)) + ", " + str(np.round(Phis_Trab[Element], 5)) + ", " + str(m[Element][0]) + ", "
            + str(m[Element][1]) + ", " + str(m[Element][2]) + "\n")
        outfile.write("*DEPVAR\n")
        outfile.write("22\n")
        outfile.write("2, DMG, Damage\n")
        outfile.write("15, BVTVc, BVTVC\n")
        outfile.write("16, BVTVt, BVTVT\n")
        outfile.write("17, PBVc, PBVC\n")
        outfile.write("18, PBVt, PBVT\n")
        # outfile.write("20, MM3, MM3(max)\n")
        # outfile.write("19, RDY, RDY_pyfl\n")
        outfile.write("22, OFvalue, OF\n")
        outfile.write("***********************************************************\n")

    zcoord = [Nodes[Node].get_coord()[2] for Node in Nodes]
    top = min(zcoord)
    bot = max(
        zcoord)  # collect max and min node coordinate along Z (I suppose that the proximal-distal axis is along Z)
    cogmod = np.mean([np.asarray(Nodes[Node].get_coord()) for Node in Nodes], axis=0)  # center of gravity of model
    outfile.write("*NSET, NSET=TOPNODES\n")
    for Node in Nodes:
        if Nodes[Node].get_coord()[2] == top:
            outfile.write(str(Node) + "\n")  # find top nodes
    outfile.write("***********************************************************\n")
    outfile.write("*NSET, NSET=BOTNODES\n")
    for Node in Nodes:
        if Nodes[Node].get_coord()[2] == bot:
            outfile.write(str(Node) + "\n")  # find bottom nodes
    # *****************************************************************
    outfile.write("***********************************************************\n")
    outfile.write("*BOUNDARY, TYPE=DISPLACEMENT\n")  # fix bottom nodes
    outfile.write("BOTNODES, 1, 3, 0\n")
    outfile.write("**\n")
    outfile.write("*NODE\n")  # create a reference node
    outfile.write("10000000, " + str(cogmod[0]) + ", " + str(cogmod[1]) + ", " + str(top) + "\n")
    outfile.write("*NSET, NSET=REF_NODE\n")
    outfile.write("10000000\n")
    outfile.write("*KINEMATIC COUPLING, REF NODE=REF_NODE\n")  # couple the reference node to the top nodes
    outfile.write("TOPNODES, 1, 6\n")
    outfile.write("**\n")
    if Config['nlgeom'] == 'on':
        outfile.write(
            "*STEP,AMPLITUDE=RAMP,UNSYMM=YES,INC=1000,NLGEOM=YES\n")  # apply displ to top nodes via reference node
    else:
        outfile.write(
            "*STEP,AMPLITUDE=RAMP,UNSYMM=YES,INC=1000,NLGEOM=NO\n")
    outfile.write("***********************************************************\n")
    outfile.write("**               INCLUDE\n")
    outfile.write("***********************************************************\n")
    outfile.write("*INCLUDE, input=" + BCs_FileName + "\n")
    outfile.write("***********************************************************\n")
    # outfile.write("*STATIC\n")
    # outfile.write(str(start_step_size) + ", " + str(time_for_displacement) + ", " + str(min_step_size) + ", " + str(
    #     max_step_size) + "\n")
    # outfile.write("*BOUNDARY, TYPE=DISPLACEMENT\n")
    # outfile.write("REF_NODE, 3, 3, " + str(load_displacement) + "\n")
    # outfile.write("REF_NODE, 1, 2, 0.0\n")
    # outfile.write("REF_NODE, 4, 6, 0.0\n")  # if you comment this line, you get the ball joint as in experiment
    # outfile.write("***********************************************************\n")
    outfile.write("*OUTPUT,FIELD\n")  # set the outputs
    outfile.write("*ELEMENT OUTPUT, POSITION=CENTROIDAL\n")  # state variables computed by the UMAT
    outfile.write("SDV2,\n")
    outfile.write("SDV15,\n")
    outfile.write("SDV16,\n")
    outfile.write("SDV17,\n")
    outfile.write("SDV18,\n")
    # outfile.write("SDV20,\n")
    outfile.write("SDV22,\n")
    outfile.write("S,\n")
    outfile.write("LE,\n")
    outfile.write("COORD,\n")
    outfile.write("*NODE OUTPUT\n")  # U: displacement, RF: reaction force
    outfile.write("U,\n")
    outfile.write("RF,\n")
    outfile.write("CF,\n")
    outfile.write("**\n")
    outfile.write("*OUTPUT, HISTORY\n")
    outfile.write("*NODE OUTPUT, NSET=REF_NODE\n")
    outfile.write("U,\n")
    outfile.write("RF,\n")
    # the axial displacement and reaction force of the reference node will be written in the dat file generated by abaqus.
    outfile.write("*NODE PRINT, NSET=REF_NODE, FREQUENCY=1, SUMMARY=NO\n")
    outfile.write("U,\n")
    outfile.write("RF\n")
    outfile.write("CF\n")
    outfile.write("*END STEP\n")
    outfile.close()

    # Writes out vtk maps of fabric for visualization
    # utils.fab2vtk(INPname, m, mm)

    return Bone
def VectorOnPlane(evect_max, evect_mid, evect_min, direction):
    """

    Parameters
    ----------
    evect_max
    evect_mid
    evect_min
    direction

    Returns
    -------
    3 numpy arrays in order evect min, evect mid, evect max
    """
    # evect_max_projected is computed by projection of direction (usually [0,0,1]) into the plane evect_max, evect_mid.
    # evect_min_projected is orthogonal to max and mid, so computed from their cross product
    # evect_mid_projected is orthogonal to max and min, so computed from their cross product

    # Old implementation
    # normal = numpy.cross(evect_max, evect_mid)
    # normalized = normal / numpy.linalg.norm(normal)
    # evect_max_projected_normalized = (
    #         direction - numpy.dot(direction, normalized) * normalized
    # )
    # evect_max_projected = evect_max_projected_normalized * numpy.linalg.norm(evect_max)
    #
    # evect_min_projected = normalized
    # evect_mid_projected = numpy.cross(evect_max_projected, normalized)
    try:
        normal = np.cross(evect_max, evect_mid)
        # evect_max_proj = direction - numpy.dot(direction, normal)
        # Projection acc. https://www.maplesoft.com/support/help/maple/view.aspx?path=MathApps%2FProjectionOfVectorOntoPlane
        evect_max_proj = direction - (np.dot(direction, normal) / np.linalg.norm(normal)**2) * normal
        evect_mid = np.cross(evect_max_proj, normal)
        evect_min = normal

        evect_max_projected = evect_max_proj / np.linalg.norm(evect_max_proj)
        evect_mid_projected = evect_mid / np.linalg.norm(evect_mid)
        evect_min_projected = evect_min / np.linalg.norm(evect_min)

        scal_max_mid = np.dot(evect_max_projected, evect_mid_projected)
        scal_max_min = np.dot(evect_max_projected, evect_min_projected)
        scal_mid_min = np.dot(evect_mid_projected, evect_min_projected)

        if scal_max_mid + scal_max_min + scal_mid_min > 0.001:
            print('projected vectors are not orthogonal!')

    except:
        evect_min_projected = evect_min
        evect_mid_projected = evect_mid
        evect_max_projected = evect_max
        print('Could not perform the vector projection in utils.vectoronplane()!')

    return evect_min_projected, evect_mid_projected, evect_max_projected
def Franoso_EigenValues_Adapted():
    """
    Returns eigenvalues of franzoso, but adapted according to Philippe Zysset for transverse isotropy.
    Main eigenvalue was taken from franzoso (E3 = 1.17) and the two others were adapted for transverse isotropy for
    all eigenvalues sum up to 3. -> E1, E2 = (3 - E3)/2
    Returns
    -------
    Evalues E1, E2, E3
    """

    E3 = 1.17
    E2 = 0.915
    E1 = 0.915

    return [E1, E2, E3]
def Compute_EigenValues_EigenVectors(i, elem, MSL_kernel_list, BVseg, projection=False):
    """
    Computes Eigenvalues and Eigenvectors for a given element using MSL_kernel_list, which is a return value of
    preprocessing.compute_local_MSL (stored in bone: dict)

    Can be used for cortical or trabecular phase. Note that for cortical phase projection = True!

    Parameters
    ----------
    i                   index of for-loop
    elem                element number of for-loop
    MSL_kernel_list:    List with areaweighted dyadic products of triangulation, after kernel homogenization
    BVseg               bone volume from segmentation for specific bone phase
    projection          Defines if projection of global Z on plane of MSL (used for cortical phase to have main
                        orientation along cortical shel

    Returns
    -------
    eval                Eigenvalues
    evect               Eigenvectors
    """
    try:
        # MSL method according to Hosseini Bone 2017
        H = 2.0 * BVseg * scipy.linalg.inv(MSL_kernel_list[elem - 1])
        if np.trace(H) > 1E-3:
            MSL = 3.0 * H / np.trace(H)
        else:
            MSL = 3.0 * H / np.trace(1E-3)
        evalue, evect = scipy.linalg.eig(MSL)
        # print(evalue, '\n', evect)
        # order eigenvalues 0=min, 1=mid, 2=max
        idx = evalue.argsort()
        evalue = evalue[idx]
        evect = evect[:, idx]
        # print(evalue, '\n', evect)
        evalue = np.array([e.real for e in evalue])
        # evect = numpy.array([evect[:, p] for p in [0, 1, 2]])
        evect = np.array(evect)
        # print(evalue, '\n', evect)

        if projection:
            # Fabric projection for cortical bone
            # vectoronplane requires inputs evect max, mid, min, so evect[2], evect[1], evect[0]
            evect[:, 0], evect[:, 1], evect[:, 2] = VectorOnPlane(evect[:, 2], evect[:, 1], evect[:, 0],
                                                                  np.array([0.0, 0.0, 1.0]))
            if np.isnan(np.sum(np.array(evect))):
                evect = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
            # E1 = 0.9010672437249067, E2 = 0.9299738069990019, E3 = 1.168958949276091
            evalue = Franoso_EigenValues_Adapted()  # Franzoso JBiomechEng. 2009 E

    except:
        # returns evalue [1, 1, 1], evect[X, Y, Z] -> min, mid, max
        evalue, evect = Isotropic_Fabric()



    return np.array(evalue), np.array(evect)
def PSL_Material_Mapping_Copy_Layers_Accurate(Bone, Config, FileNames):

    """
    Adapted from Denis's preprocessing_SA.py -> PSL_material_mapping_copy_layers_accurate
    Material Mapping, including PSL ghost padding layers as copy of most distal and proximal layers
    For accurate PSL pipeline
    Additionaly, the optional BMC conversion can be specified in config.yaml. This function will conserve BMC from
    image to hFE model to ensure, no mass conservation.
    Debuged and checked for right orientations!

    Included new MSL fabric evaluation with separation between cortex and trabecular bone

    Parameters
    ----------
    bone
    config
    umat_parameters
    filenames

    Returns
    -------

    """

    # Get images
    BVTV_Scaled = Bone['BVTV_Scaled']
    BMD_array = Bone['BMD_Scaled']
    CORTMASK_Array = Bone['CORTMASK_Array']
    TRABMASK_Array = Bone['TRABMASK_Array']
    SEG_Array = Bone['SEG_Array']

    # Create images for material mapping
    BVTVc = np.copy(BVTV_Scaled)
    BVTVc[CORTMASK_Array == 0] = 0
    BVTVt = np.copy(BVTV_Scaled)
    BVTVt[TRABMASK_Array == 0] = 0
    SEG_Array[SEG_Array > 0] = 1
    SEGc_Masked = np.copy(SEG_Array)
    SEGc_Masked[CORTMASK_Array == 0] = 0
    SEGt_Masked = np.copy(SEG_Array)
    SEGt_Masked[TRABMASK_Array == 0] = 0

    # Get bone values
    FEelSize = Bone['FEelSize']
    Spacing = Bone['Spacing']
    Elements = Bone['Elements']
    Nodes = Bone['Nodes']
    Elements_Sets = Bone['Elements_Sets']
    EigenValues = Bone['EigenValues']
    EigenVectors = Bone['EigenVectors']
    ROI_BVTV_Size_Trab = Config['ROI_BVTV_Size_Trab']
    ROI_BVTV_Size_Cort = Config['ROI_BVTV_Size_Cort']

    #Local fabric type: Computed by compute_local_MSL and assign_MSL_triangulation and
    MSL_kernel_list_cort = Bone['MSL_Kernel_List_Cort']
    MSL_kernel_list_trab = Bone['MSL_Kernel_List_Trab']

    # Material mapping procedure
    Elements_Sets['BONE'] = []
    # local fabric is evaluated in cort and trab at the moment!
    Rhos_Cort = {}
    RHOc_corrected = {}  # RHO corrected by PBV (RHO * PHI)
    Rhos_Trab = {}
    RHOt_corrected = {}  # RHO corrected by PBV (RHO * PHI)
    Rhos_Cort_FE = {}  # RHO of only FE element (ROI = FEelement)
    Rhos_Trab_FE = {}  # RHO of only FE element (ROI = FEelement)
    Phis_Cort = {}
    Phis_Trab = {}
    mm = {}
    m = {}
    BVTVcortseg = {}
    BVTVtrabseg = {}
    BVTVcortseg_elem = {}
    BVTVtrabseg_elem = {}
    DOA = {}
    COGs = {}

    # Read boundary condition variables
    BCs_FileName = FileNames['BCs']

    only_cort_element = 0
    only_trab_element = 0
    mixed_phase_element = 0

    # Extract transforms parameters
    if Config['Registration']:
        I = sitk.ReadImage(FileNames['Common'])
        Center = np.array(I.GetSize()) / 2 * np.array(I.GetSpacing())
        C1 = Center + np.array(I.GetOrigin())
        R1 = np.array([[-1, 0, 0],[0, 1, 0],[0, 0, -1]])
        T1 = np.array([0, 0, 0])

        IT = sitk.ReadTransform(FileNames['InitialTransform'])
        C2 = np.array(IT.GetFixedParameters()[:-1], 'float')
        P2 = IT.GetParameters()
        R2 = RotationMatrix(-P2[0], -P2[1], -P2[2])
        T2 = -np.array(P2[3:])

        FT = GetParameterMap(FileNames['Transform'])
        C3 = np.array(FT['CenterOfRotationPoint'], 'float')
        P3 = np.array(FT['TransformParameters'],'float')
        R3 = RotationMatrix(-P3[0], -P3[1], -P3[2])
        T3 = -np.array(P3[3:])

    # ---------------------------------------------------------------------------
    for i, Element in enumerate(Elements):
        # 2.1 Compute center of gravity
        try:
            COG = np.mean([np.asarray(Nodes[Node].get_coord()) for Node in Elements[Element].get_nodes()], axis=0)  # center of gravity of each element
        except:
            print(i)
            
        # Transform Center of gravity from uCT to HRpQCT space
        if Config['Registration']:
            COG_Inv = InverseTransformPoints(np.array([COG]), C1, R1, T1, C2, R2, T2, C3, R3, T3)[0]
        else:
            COG_Inv = COG
        # 2.2 compute PHI from masks
        Phi_Cort, Xc, Yc, Zc = Compute_Phi(COG_Inv, Spacing, FEelSize[0], CORTMASK_Array)
        Phi_Trab, Xt, Yt, Zt = Compute_Phi(COG_Inv, Spacing, FEelSize[0], TRABMASK_Array)

        if COG_Inv[0] < 0 or COG_Inv[1] < 0 or COG_Inv[2] < 0:
            Phi_Cort = 0.0
            Phi_Trab = 0.0

        # If an element holds a part of a mask
        if Phi_Cort > 0.0 or Phi_Trab > 0.0:

            # 2.3 Compute BVTV
            Rho_Cort, Rho_Trab = Compute_BVTV_TwoPhases(COG_Inv, Spacing, ROI_BVTV_Size_Cort, ROI_BVTV_Size_Trab, SEG_Array, CORTMASK_Array, TRABMASK_Array, Phi_Cort, Phi_Trab)


            # Apply segmentation correction
            if Phi_Cort > 0.0:
                Rho_Cort = Rho_Cort*0.651 + 0.056462
            if Phi_Trab > 0.0:
                Rho_Trab = Rho_Trab*0.651 + 0.056462

            # Correction curve from Varga et al. 2009 for XCTI, added by MI
            if Spacing[0] == 0.082:
                if Phi_Cort > 0.0:
                    Rho_Cort = Rho_Cort*0.745745 - 0.0209902
                if Phi_Trab > 0.0:
                    Rho_Trab = Rho_Trab*0.745745 - 0.0209902

            Rho_Cort_FE = Compute_BVTV_FEel(COG_Inv, Spacing, FEelSize, SEG_Array, CORTMASK_Array)
            Rho_Trab_FE = Compute_BVTV_FEel(COG_Inv, Spacing, FEelSize, SEG_Array, TRABMASK_Array)

            # if option is true in config, correct FE mesh to not have any holes. Minimum BVTV is 1% for both phases
            if Config['All_Mask']:
                if Phi_Cort > 0.0 and Rho_Cort < 0.01:
                    Rho_Cort = 0.01
                if Phi_Trab > 0.0 and Rho_Trab < 0.01:
                    Rho_Trab = 0.01

            # Check if element holds bone or if mask is empty
            if Phi_Cort * Rho_Cort or Rho_Trab * Phi_Trab > 0.0:
                Elements_Sets['BONE'].append(Element)

                Phis_Cort[Element] = Phi_Cort
                Phis_Trab[Element] = Phi_Trab
                Rhos_Cort[Element] = Rho_Cort
                Rhos_Trab[Element] = Rho_Trab
                Rhos_Cort_FE[Element] = Rho_Cort_FE
                Rhos_Trab_FE[Element] = Rho_Trab_FE

                # Assign computed values to element
                RHOc_corrected[Element] = Rhos_Cort[Element] * Phis_Cort[Element]
                RHOt_corrected[Element] = Rhos_Cort[Element] * Phis_Trab[Element]

                # Compute elemental BVTV from segmentation
                # Method computePHI can be used on segmentation instead of mask
                BVTVcortseg_elem[Element], Xcs, Ycs, Zcs = Compute_Phi(COG_Inv, Spacing, ROI_BVTV_Size_Cort, SEGc_Masked)
                BVTVtrabseg_elem[Element], Xcs, Ycs, Zcs = Compute_Phi(COG_Inv, Spacing, ROI_BVTV_Size_Trab, SEGt_Masked)
                try:
                    BVTVcortseg[Element] = BVTVcortseg_elem[Element] / Phis_Cort[Element]
                except:
                    BVTVcortseg[Element] = 0
                try:
                    BVTVtrabseg[Element] = BVTVtrabseg_elem[Element] / Phis_Trab[Element]
                except:
                    BVTVtrabseg[Element] = 0

                BVcortseg = BVTVcortseg_elem[Element] * FEelSize[0] ** 3
                BVtrabseg = BVTVtrabseg_elem[Element] * FEelSize[0] ** 3

                # Evaluate Fabric using MSL
                # Element contains only trabecular bone
                if Phi_Cort == 0.0:
                    only_trab_element = only_trab_element + 1
                    EigenValues, EigenVectors = Compute_EigenValues_EigenVectors(i, Element, MSL_kernel_list_trab, BVtrabseg, projection=False)

                # Element contains only cortical bone
                elif Phi_Trab == 0.0:
                    only_cort_element = only_cort_element + 1
                    EigenValues, EigenVectors = Compute_EigenValues_EigenVectors(i, Element, MSL_kernel_list_cort, BVcortseg, projection=True)

                # Mixed phase Elementents
                elif Phi_Trab > 0 and Phi_Cort > 0:
                        mixed_phase_element = mixed_phase_element + 1
                        evalue_cort, evect_cort = Compute_EigenValues_EigenVectors(i, Element, MSL_kernel_list_cort, BVcortseg, projection=True)
                        evalue_trab, evect_trab = Compute_EigenValues_EigenVectors(i, Element, MSL_kernel_list_trab, BVtrabseg, projection=False)

                        # MSL superposition for mixed phase elements
                        MSL_cort = evect_cort.dot(np.diag(evalue_cort)).dot(evect_cort.T)
                        MSL_trab = evect_trab.dot(np.diag(evalue_trab)).dot(evect_trab.T)

                        # Volume fraction based superposition
                        # If PHIs don't add up to one, air is added as an isotropic phase
                        MSL_air = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
                        MSL_mixed = Phi_Cort * MSL_cort + Phi_Trab * MSL_trab + (1 - Phi_Cort - Phi_Trab) * MSL_air

                        EigenValues, EigenVectors = scipy.linalg.eig(MSL_mixed)
                        # order eigenvalues 0=min, 1=mid, 2=max
                        idx = EigenValues.argsort()
                        EigenValues = EigenValues[idx]
                        EigenVectors = EigenVectors[:, idx]
                        EigenValues = [e.real for e in EigenValues]
                        EigenVectors = [EigenVectors[:, p] for p in [0, 1, 2]]

                # Transform eigen vectors from HRpQCT to uCT space
                if Config['Registration']:
                    for iVector, Vector in enumerate(EigenVectors):
                        RV = np.dot(R1, Vector)
                        RV = np.dot(R2, RV)
                        RV = np.dot(R3, RV)
                        EigenVectors[iVector] = RV

                m[Element] = EigenValues
                mm[Element] = EigenVectors
                DOA[Element] = EigenValues[0] / EigenValues[2]
                COGs[Element] = COG

        Time.Update((4 + i/(len(Elements) - 1)*4)/10, 'Material mapping')

    if Config['Echo'] == True:
        print("\nThe following number of elements were mapped for each phase\n  - cortical:   %5d \n"
          "  - trabecular: %5d \n  - mixed:      %5d" % (only_cort_element, only_trab_element, mixed_phase_element))

    # conversion to np array for calculation of BVTV and selection of only elements contained in ELSET BONE
    # -----------------------------------------------------------------------------------------------------
    # these arrays are only used for computations in the summary file, and not for the abaqus input file.
    # Therefore, only elements belonging to ELSET BONE are considered.

    # Cortical bone
    PHIc_array = np.array([Phis_Cort[k] for k in Elements_Sets['BONE'] if k in Phis_Cort])
    RHOc_orig_array = np.array([Rhos_Cort[k] for k in Elements_Sets['BONE'] if k in Rhos_Cort])
    RHOc_FE_array = np.array([Rhos_Cort_FE[k] for k in Elements_Sets['BONE'] if k in Rhos_Cort_FE])

    # Trabecular bone
    PHIt_array = np.array([Phis_Trab[k] for k in Elements_Sets['BONE'] if k in Phis_Trab])
    RHOt_orig_array = np.array([Rhos_Trab[k] for k in Elements_Sets['BONE'] if k in Rhos_Trab])
    RHOt_FE_array = np.array([Rhos_Trab_FE[k] for k in Elements_Sets['BONE'] if k in Rhos_Trab_FE])

    cogs_array = np.array([COGs[k] for k in Elements_Sets['BONE'] if k in COGs])
    DOA_array = np.array(DOA.values())

    # Create elements and nodes for Abaqus Input File
    Elements = {Element: Elements[Element] for Element in Elements_Sets['BONE']}
    Bone_Elements = Elements


    # BMC compensation for all BVTV values in order to conserve bone mass during homogenization
    BMC_reco_c = np.sum(BMD_array[CORTMASK_Array > 0]) * Spacing[0] ** 3 / 1000
    BMC_sim_c = np.sum(RHOc_orig_array * PHIc_array * FEelSize[0] ** 3) * 1200 / 1000
    lambda_BMC_c = BMC_reco_c / BMC_sim_c

    BMC_reco_t = np.sum(BMD_array[TRABMASK_Array > 0]) * Spacing[0] ** 3 / 1000
    BMC_sim_t = np.sum(RHOt_orig_array * PHIt_array * FEelSize[0] ** 3) * 1200 / 1000
    lambda_BMC_t = BMC_reco_t / BMC_sim_t

    # 2) Copy RHOc and RHOt dict to save uncompensated BVTV values
    Rho_Cort_Original = copy.deepcopy(Rhos_Cort)  # use deepcopy to avoid shallow copy
    Rho_Trab_Original = copy.deepcopy(Rhos_Trab)

    # 3) Compensate RHOb BVTV values (no BMC conservation)
    for Element in Bone_Elements:
        Rhos_Cort[Element] = Rho_Cort_Original[Element]
        Rhos_Trab[Element] = Rho_Trab_Original[Element]

    RHOc_array = np.array([Rhos_Cort[k] for k in Elements_Sets['BONE'] if k in Rhos_Cort])
    RHOt_array = np.array([Rhos_Trab[k] for k in Elements_Sets['BONE'] if k in Rhos_Trab])

    Nodes = {Node: Nodes[Node] for Element in Elements for Node in Elements[Element].get_nodes()}

    # Write mesh to Abaqus input file
    INPname = FileNames['INPname']
    WriteAbaqus(INPname, None, Nodes, None, Elements, Elements_Sets, NscaResults=None)

    marray = np.real(np.mean([np.asarray(m[Element]) for Element in m.keys()], axis=0))
    mmarray1 = np.real(np.mean([np.asarray(mm[Element][0]) for Element in m.keys()], axis=0))
    mmarray2 = np.real(np.mean([np.asarray(mm[Element][1]) for Element in m.keys()], axis=0))
    mmarray3 = np.real(np.mean([np.asarray(mm[Element][2]) for Element in m.keys()], axis=0))

    if Config['Echo'] == True:
        Print_Memory_Usage()

    # Store variables to bone dict
    Bone['RHOc_array'] = RHOc_array
    Bone['RHOt_array'] = RHOt_array
    Bone['RHOc_orig_array'] = RHOc_orig_array
    Bone['RHOt_orig_array'] = RHOt_orig_array
    Bone['PHIc_array'] = PHIc_array
    Bone['PHIt_array'] = PHIt_array
    Bone['RHOc_FE_array'] = RHOc_FE_array
    Bone['RHOt_FE_array'] = RHOt_FE_array
    Bone['Elements'] = Elements
    Bone['Bone_Elements'] = Bone_Elements
    Bone['Nodes'] = Nodes
    Bone['Elements_Sets'] = Elements_Sets
    Bone['marray'] = marray
    Bone['mmarray1'] = mmarray1
    Bone['mmarray2'] = mmarray2
    Bone['mmarray3'] = mmarray3
    Bone['cogs'] = cogs_array
    Bone['CoarseFactor'] = Bone['FEelSize'][0] / Bone['Spacing'][0]
    Bone["DOA"] = DOA_array
    Bone['m_dict'] = m
    Bone['mm_dict'] = mm
    Bone['COGs'] = COGs

    # Write elements and material properties to input file
    Time.Update(9/10, 'Update input file')
    outfile = open(INPname, 'a')
    outfile.write("***********************************************************\n")

    # Write node sets as elements with material properties
    for Element in Elements:
        outfile.write("*ELEMENT, TYPE=C3D8, ELSET=Elset" + str(Element) + "\n")
        outfile.write(str(Element) + ", " + str(Elements[Element].get_nodes()).replace("[", "").replace("]", "") + "\n")
        outfile.write("**POSITION: X = " + str(COGs[Element][0]) + " Y = " + str(COGs[Element][1]) + " Z = " + str(
            COGs[Element][2]) + "\n")
        outfile.write("*ORIENTATION, NAME=Orient" + str(Element) + "\n")
        outfile.write(
            str(mm[Element][0][0]) + ", " + str(mm[Element][1][0]) + ", " + str(mm[Element][2][0]) + ", " + str(mm[Element][0][1])
            + ", " + str(mm[Element][1][1]) + ", " + str(mm[Element][2][1]) + "\n") # evect for eval[1] is [:,1]!
        outfile.write("1, 0.\n")
        outfile.write("*SOLID SECTION, ELSET=Elset" + str(Element) + ",  MATERIAL=Mat" + str(Element) + ", ORIENTATION=Orient"
                      + str(Element) + "\n")
        outfile.write("*MATERIAL, NAME=Mat" + str(Element) + "\n")
        outfile.write("*USER MATERIAL, CONSTANTS=7, UNSYMM, TYPE=MECHANICAL\n")
        outfile.write("**BVTVcort, BVTVtrab, BPVcort, BPVtrab, eigenvalue min, eigenvalue mid, eigenvalue max\n")
        outfile.write(
            str(np.round(Rhos_Cort[Element], 5)) + ", " + str(np.round(Rhos_Trab[Element], 5)) + ", " + str(
                np.round(Phis_Cort[Element], 5)) + ", " + str(np.round(Phis_Trab[Element], 5)) + ", " + str(m[Element][0]) + ", "
            + str(m[Element][1]) + ", " + str(m[Element][2]) + "\n")
        outfile.write("*DEPVAR\n")
        outfile.write("31\n")
        outfile.write("2, DMG, Damage\n")
        outfile.write("15, BVTVc, BVTVC\n")
        outfile.write("16, BVTVt, BVTVT\n")
        outfile.write("17, PBVc, PBVC\n")
        outfile.write("18, PBVt, PBVT\n")
        outfile.write("22, OFvalue, OF\n")
        outfile.write("23, F11, F11\n")
        outfile.write("24, F12, F12\n")
        outfile.write("25, F13, F13\n")
        outfile.write("26, F21, F21\n")
        outfile.write("27, F22, F22\n")
        outfile.write("28, F23, F23\n")
        outfile.write("29, F31, F31\n")
        outfile.write("30, F32, F32\n")
        outfile.write("31, F33, F33\n")


        outfile.write("***********************************************************\n")

    zcoord = [Nodes[Node].get_coord()[2] for Node in Nodes]
    top = min(zcoord)
    bot = max(
        zcoord)  # collect max and min node coordinate along Z (I suppose that the proximal-distal axis is along Z)
    cogmod = np.mean([np.asarray(Nodes[Node].get_coord()) for Node in Nodes], axis=0)  # center of gravity of model
    outfile.write("*NSET, NSET=TOPNODES\n")
    for Node in Nodes:
        if Nodes[Node].get_coord()[2] == top:
            outfile.write(str(Node) + "\n")  # find top nodes
    outfile.write("***********************************************************\n")
    outfile.write("*NSET, NSET=BOTNODES\n")
    for Node in Nodes:
        if Nodes[Node].get_coord()[2] == bot:
            outfile.write(str(Node) + "\n")  # find bottom nodes
    outfile.write("***********************************************************\n")
    outfile.write("*BOUNDARY, TYPE=DISPLACEMENT\n")  # fix bottom nodes
    outfile.write("BOTNODES, 1, 3, 0\n")
    outfile.write("**\n")
    outfile.write("*NODE\n")  # create a reference node
    outfile.write("10000000, " + str(cogmod[0]) + ", " + str(cogmod[1]) + ", " + str(top) + "\n")
    outfile.write("*NSET, NSET=REF_NODE\n")
    outfile.write("10000000\n")
    outfile.write("*KINEMATIC COUPLING, REF NODE=REF_NODE\n")  # couple the reference node to the top nodes
    outfile.write("TOPNODES, 1, 6\n")
    outfile.write("**\n")
    if Config['nlgeom'] == 'YES':
        outfile.write(
            "*STEP,AMPLITUDE=RAMP,UNSYMM=YES,INC=" + str(Config['Max_Increments']) + ",NLGEOM=YES\n")  # apply displ to top nodes via reference node
    else:
        outfile.write(
            "*STEP,AMPLITUDE=RAMP,UNSYMM=YES,INC=" + str(Config['Max_Increments']) + ",NLGEOM=NO\n")
    outfile.write("***********************************************************\n")
    outfile.write("**               INCLUDE\n")
    outfile.write("***********************************************************\n")
    outfile.write("*INCLUDE, input=" + BCs_FileName + "\n")
    outfile.write("***********************************************************\n")
    outfile.write("*OUTPUT,FIELD\n")  # set the outputs
    outfile.write("*ELEMENT OUTPUT, POSITION=CENTROIDAL\n")  # state variables computed by the UMAT
    outfile.write("SDV2,\n")
    outfile.write("SDV15,\n")
    outfile.write("SDV16,\n")
    outfile.write("SDV17,\n")
    outfile.write("SDV18,\n")
    outfile.write("SDV22,\n")
    outfile.write("SDV23,\n")
    outfile.write("SDV24,\n")
    outfile.write("SDV25,\n")
    outfile.write("SDV26,\n")
    outfile.write("SDV27,\n")
    outfile.write("SDV28,\n")
    outfile.write("SDV29,\n")
    outfile.write("SDV30,\n")
    outfile.write("SDV31,\n")
    outfile.write("S,\n")
    outfile.write("LE,\n")
    outfile.write("COORD,\n")
    outfile.write("*NODE OUTPUT\n")  # U: displacement, RF: reaction force
    outfile.write("U,\n")
    outfile.write("RF,\n")
    outfile.write("CF,\n")
    outfile.write("**\n")
    outfile.write("*OUTPUT, HISTORY\n")
    outfile.write("*NODE OUTPUT, NSET=REF_NODE\n")
    outfile.write("U,\n")
    outfile.write("RF,\n")

    # Axial displacement and reaction force of the reference node will be written in the dat file generated by abaqus.
    outfile.write("*NODE PRINT, NSET=REF_NODE, FREQUENCY=1, SUMMARY=NO\n")
    outfile.write("U,\n")
    outfile.write("RF\n")
    outfile.write("CF\n")
    outfile.write("*END STEP\n")
    outfile.close()

    return Bone
def AIM2FE_SA_PSL(Config, Sample, Directories):

    """
    Convert an AIM file to a HDF5 file
    Adapted from Denis's aim2fe_SA_PSL.py
    """

    FileNames = Set_FileNames(Config, Sample, Directories)

    if Config['Echo'] == True:
        print(yaml.dump(FileNames, default_flow_style=False))
        Print_Memory_Usage()

    # Create bone dictionary, storing arrays and variables
    Bone = {}

    # Read AIM images and image parameters
    Time.Update(1/10, 'Read Images')
    Bone = Read_Image_Parameters(FileNames, Bone)
    Image_List = ['BMD', 'SEG', 'CORTMASK', 'TRABMASK']

    for Item in Image_List:
        Bone = Read_AIM(Item, FileNames, Bone)
        Bone = Adjust_Image(Item, Bone, Config, 'Crop')

    if Config['Echo'] == True:
        Print_Memory_Usage()

    # If registration, read common image and mask arrays
    if Config['Registration']:
        Time.Update(2/10, 'Common region')
        Bone = CommonRegion(Bone, FileNames['Common'], FileNames['Common_uCT'])

    if Config['Echo'] == True:
        Print_Memory_Usage()

    # Prepare material mapping
    Time.Update(2/10, 'Prepare mapping')
    ImageType = Config['ImageType']
    Bone = Calculate_BVTV(Bone, Config, ImageType)
    Bone = Generate_Mesh(Bone, FileNames, Config)
    Bone = Calculate_Iso_Fabric(Bone)

    # 4 Material mapping
    # Compute MSL kernel list
    Time.Update(3/10, 'Compute MSL')
    Bone = Compute_Local_MSL(Bone, Config, FileNames)
    if Config['Echo'] == True:
        Print_Memory_Usage()

    # ---------------------------------------------------------------------------------
    # Ghost layer mode
    if Config['Isotropic_Cortex']:
        Bone = PSL_Material_Mapping_Copy_Layers_Iso_Cort(Bone, Config, FileNames)
    else:
        Bone = PSL_Material_Mapping_Copy_Layers_Accurate(Bone, Config, FileNames)
    
    if Config['Echo'] == True:
        Print_Memory_Usage()

    return

#%%
def Main(ConfigFile):

    # Read config and store to dictionary
    Config = ReadConfigFile(ConfigFile)
    if Config['Echo'] == True:
        print(yaml.dump(Config, default_flow_style=False))

    # Directories
    WD, DD, SD, RD = SetDirectories('FRACTIB')
    Directories = {}
    Directories['AIM'] = DD / '02_uCT/'
    Directories['FEA'] = RD / '03_hFE/'
    Directories['Localization'] = RD / '05_Localizations/'
    Directories['Scripts'] = SD / '3_hFE/'
    Directories['BCs'] = SD / '3_hFE' / 'BCs/'

    # File names and folders
    GrayScale_FileNames = Config['GrayScale_FileNames']
    Folder_IDs = Config['Folder_IDs']

    for iS, Sample in enumerate(GrayScale_FileNames):

        Text = 'Sample ' + str(iS+1) + '/' + str(len(GrayScale_FileNames))
        Time.Process(1, Text)

        # Set paths
        Folder = Folder_IDs[Sample]
        InputFileName = "{}.inp".format('Simulation')
        InputFile = str(Directories['FEA'] / Folder / InputFileName)

        # Perform material mapping
        AIM2FE_SA_PSL(Config, Sample, Directories)

        # Write load case
        FileName = str(RD / '02_Experiment' / Folder / 'MatchedSignals.csv')
        Step1Name = str(Directories['FEA'] / Folder / 'Loading.inp')
        Step2Name = str(Directories['FEA'] / Folder / 'Unloading.inp')
        
        # Truncate experiment
        Experiment = pd.read_csv(FileName)
        Peaks, Properties = sig.find_peaks(Experiment['FZ'], prominence=1)
        MaxForce = Experiment['FZ'].idxmin()
        MaxDisp = Experiment['Z'].idxmax()
        DeltaTime = 10
        DeltaIndex = np.argmin(np.abs(Experiment['T']-DeltaTime))
        Start = Peaks[Peaks < MaxForce - DeltaIndex][-1]
        Stop = Peaks[Peaks > MaxDisp][0]
        Experiment = Experiment[Start:Stop].reset_index(drop=True)
        Experiment -= Experiment.loc[0]

        # Write simulation steps
        MaxDisp = round(Experiment['Z'].max(), 3)
        Abaqus.WriteRefNodeBCs(Step1Name, [3], [MaxDisp], Config['Control'])
        EndDisp = round(Experiment['Z'].values[-1], 3)
        Abaqus.AddStep(InputFile, Step2Name, [3], [EndDisp])

        Time.Process(0, Text)
        
    return


#%%
if __name__ == '__main__':

    # Initiate the parser with a description
    Parser = argparse.ArgumentParser(description=Description, formatter_class=argparse.RawDescriptionHelpFormatter)

    # Add long and short argument
    ScriptVersion = Parser.prog + ' version ' + Version
    Parser.add_argument('-v', '--Version', help='Show script version', action='version', version=ScriptVersion)
    Parser.add_argument('File', help='Configuration file (required)', type=str)

    # Read arguments from the command line
    Arguments = Parser.parse_args()

    Main(Arguments.File)
