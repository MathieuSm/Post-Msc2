#%% #!/usr/bin/env python3
# Initialization

Version = '01'

Description = """
    Script used to perform pre/post-test registration in 3 steps:
        1. Masks rigid registration
        2. Masks affine registration
        3. Gray scale B-Spline registration

    Version Control:
        01 - Original script

    Author: Mathieu Simon
            ARTORG Center for Biomedical Engineering Research
            SITEM Insel, University of Bern

    Date: December 2022
    """

#%% Imports
# Modules import

import yaml
import numba
import argparse
from Utils import *
from numba import njit

Read.Echo = False
Registration.Echo = False
Show.ShowPlot = False

#%% Functions
# Define functions
def ReadConfigFile(Filename, Echo=False):

    """ Read configuration file and store to dictionary """

    if Echo:
        print('\n\nReading configuration file', Filename)
    
    with open(Filename, 'r') as File:
        Configuration = yaml.load(File, Loader=yaml.FullLoader)

    return Configuration
def AdjustImageSize(Image, CoarseFactor, CropZ='Crop'):

    """
    Adapted from Denis's utils_SA.py
    Images are adjusted according to CropType:
    0 = CropType.expand     (Expand image by copying layers)
    1 = CropType.crop       (Crop image)
    2 = CropType.variable   (Either crop or expand, depending on what includes less layers)
    """

    # Get array
    Array = sitk.GetArrayFromImage(Image)
    Array = Array.transpose(2, 1, 0)

    # Measure image shape
    IMDimX = np.shape(Array)[0]
    IMDimY = np.shape(Array)[1]
    IMDimZ = np.shape(Array)[2]

    AddDimX = CoarseFactor - (IMDimX % CoarseFactor)
    AddDimY = CoarseFactor - (IMDimY % CoarseFactor)

    # adjust in x and y direction
    Shape_Diff = [AddDimX, AddDimY]
    IMG_XY_Adjusted = np.lib.pad(Array,
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

    Image_Adjusted = sitk.GetImageFromArray(Image_Adjusted.transpose(2, 1, 0))
    Image_Adjusted.SetSpacing(Image.GetSpacing())
    Image_Adjusted.SetOrigin(Image.GetOrigin())
    Image_Adjusted.SetDirection (Image.GetDirection())

    return Image_Adjusted

@njit
def Decomposition(JacobianArray):

    # ProcessTiming(1, 'Decompose Jacobian of deformation')

    Terms = JacobianArray.shape[-1]
    ArrayShape = JacobianArray.shape[:-1]

    if Terms == 4:

        SphericalCompression = np.zeros(ArrayShape)
        IsovolumicDeformation = np.zeros(ArrayShape)
        # HydrostaticStrain = np.zeros(ArrayShape)
        # VonMises_Strain = np.zeros(ArrayShape)
        # MaxShear = np.zeros(ArrayShape)

        # ProcessLength = ArrayShape[0] * ArrayShape[1]
        # Progress = 0
        for j in range(0, ArrayShape[0]):
            for i in range(0, ArrayShape[1]):
                F_d = JacobianArray[j, i, :].reshape((2,2))

                ## Unimodular decomposition of F
                J = np.linalg.det(F_d)
                SphericalCompression[j, i] = J

                if J > 0:
                    F_tilde = J ** (-1 / 3) * F_d
                    Norm_F_tilde = np.linalg.norm(F_tilde)
                else:
                    Norm_F_tilde = 0.0

                IsovolumicDeformation[j, i] = Norm_F_tilde

                # ## Optional: decomposition of F_tilde
                # R_tilde, U_tilde = polar(F_tilde)
                # Norm_U_tilde = np.sqrt(np.sum(U_tilde ** 2))

                ## Hydrostatic and deviatoric strain
                # I_d = np.matrix(np.eye(F_d.shape[0]))
                # E = 1/2 * (F_d.T * F_d - I_d)
                # Hydrostatic_E = -1/3 * np.trace(E) * I_d
                # Deviatoric_E = E - Hydrostatic_E
                #
                # HydrostaticStrain[k,j,i] = Hydrostatic_E[0,0]
                # MaxShear[k,j,i] = E.diagonal().max() - E.diagonal().min()
                #
                # VM_Strain = np.sqrt(3/2) * np.linalg.norm(Deviatoric_E)
                # VonMises_Strain[k,j,i] = VM_Strain

                # Progress += 1
                # ProgressNext(Progress/ProcessLength*20)

    elif Terms == 9:

        SphericalCompression = np.zeros(ArrayShape)
        IsovolumicDeformation = np.zeros(ArrayShape)
        # HydrostaticStrain = np.zeros(ArrayShape)
        # VonMises_Strain = np.zeros(ArrayShape)
        # MaxShear = np.zeros(ArrayShape)

        # ProcessLength = ArrayShape[0] * ArrayShape[1] * ArrayShape[2]
        # Progress = 0
        for k in range(0, ArrayShape[0]):
            for j in range(0, ArrayShape[1]):
                for i in range(0, ArrayShape[2]):

                    F_d = JacobianArray[k, j, i, :].reshape((3, 3))

                    ## Unimodular decomposition of F
                    J = np.linalg.det(F_d)
                    SphericalCompression[k, j, i] = J

                    if J > 0:
                        F_tilde = J ** (-1 / 3) * F_d
                        Norm_F_tilde = np.linalg.norm(F_tilde)
                    else:
                        Norm_F_tilde = 0.0

                    IsovolumicDeformation[k, j, i] = Norm_F_tilde

                    # ## Optional: decomposition of F_tilde
                    # R_tilde, U_tilde = polar(F_tilde)
                    # Norm_U_tilde = np.sqrt(np.sum(U_tilde ** 2))

                    ## Hydrostatic and deviatoric strain
                    # I_d = np.matrix(np.eye(F_d.shape[0]))
                    # E = 1/2 * (F_d.T * F_d - I_d)
                    # Hydrostatic_E = -1/3 * np.trace(E) * I_d
                    # Deviatoric_E = E - Hydrostatic_E
                    #
                    # HydrostaticStrain[k,j,i] = Hydrostatic_E[0,0]
                    # MaxShear[k,j,i] = E.diagonal().max() - E.diagonal().min()
                    #
                    # VM_Strain = np.sqrt(3/2) * np.linalg.norm(Deviatoric_E)
                    # VonMises_Strain[k,j,i] = VM_Strain
                    
                    # Progress += 1
                    # ProgressNext(Progress/ProcessLength*20)

    return SphericalCompression, IsovolumicDeformation

def DecomposeJacobian(JacobianImage):

    # Determine 2D of 3D jacobian array
    JacobianArray = sitk.GetArrayFromImage(JacobianImage)
    
    print('\nDecompose Jacobian')
    Tic = time.time()
    SC, ID = Decomposition(JacobianArray)
    Toc = time.time()
    PrintTime(Tic, Toc)

    SphericalCompression = sitk.GetImageFromArray(SC)
    IsovolumicDeformation = sitk.GetImageFromArray(ID)

    for Image in [SphericalCompression, IsovolumicDeformation]:
        Image.SetSpacing(JacobianImage.GetSpacing())
        Image.SetDirection(JacobianImage.GetDirection())
        Image.SetOrigin(JacobianImage.GetOrigin())

    return SphericalCompression, IsovolumicDeformation


#%% Main
# Main code

def Main(Arguments):

    # Set directories
    WD, DD, SD, RD = SetDirectories('FRACTIB')
    SampleList = pd.read_csv(str(DD / 'SampleList.csv'))
    for Index, Sample in enumerate(SampleList['Internal ID']):

        Time.Process(1, Sample)

        DataDir = DD / '02_uCT' / Sample
        ResultsDir = RD / '04_Registration' / Sample
        os.makedirs(ResultsDir, exist_ok=True)

        # Read hFE config file
        ConfigFile = str(SD / '3_hFE' / 'ConfigFile.yaml')
        Config = ReadConfigFile(ConfigFile)

        # Read AIMs 
        Time.Update(1/9, 'Read AIMs')

        Files = [File for File in os.listdir(DataDir) if File.endswith('DOWNSCALED.AIM')]
        Files.sort()

        Otsu = sitk.OtsuMultipleThresholdsImageFilter()
        Otsu.SetNumberOfThresholds(2)

        for iFile, File in enumerate(Files):

            Image = Read.AIM(str(DataDir / File))[0]
            Spacing = Image.GetSpacing()
            Time.Update((2+iFile)/9, 'Adjust size')

            Mask = Otsu.Execute(Image)
            Array = sitk.GetArrayFromImage(Mask)
            Array[Array < 2] = 0
            Array[Array > 0] = 1
            Mask = sitk.GetImageFromArray(Array)
            Mask.SetSpacing(Spacing)

            if iFile == 0: 
                CoarseFactor = int(round(Config['ElementSize'] / Spacing[0]))
                PreI = AdjustImageSize(Image, CoarseFactor)
                PreM = AdjustImageSize(Mask, CoarseFactor)
            else:
                PostI = AdjustImageSize(Image, CoarseFactor)
                PostM = AdjustImageSize(Mask, CoarseFactor)

        # Downscale images to reduce computational cost
        DownFactor = 2
        R_PreI = Resample(PreI,Factor=DownFactor)
        R_PreM = Resample(PreM,Factor=DownFactor)
        R_PostI = Resample(PostI,Factor=DownFactor)
        R_PostM = Resample(PostM,Factor=DownFactor)


        # Pad for transformations    
        Pad = CoarseFactor
        P_PreI = sitk.ConstantPad(R_PreI, (Pad, Pad, Pad), (Pad, Pad, Pad))
        P_PreM = sitk.ConstantPad(R_PreM, (Pad, Pad, Pad), (Pad, Pad, Pad))
        P_PostI = sitk.ConstantPad(R_PostI, (Pad, Pad, Pad), (Pad, Pad, Pad))
        P_PostM = sitk.ConstantPad(R_PostM, (Pad, Pad, Pad), (Pad, Pad, Pad))


        # Align centers of gravity
        Time.Update(4/9, 'Align COG')
        CenterType = sitk.CenteredTransformInitializerFilter.MOMENTS

        IniTransform = sitk.CenteredTransformInitializer(P_PreI, P_PostI, sitk.Euler3DTransform(), CenterType)
        P_PostI = sitk.Resample(P_PostI, P_PreI, IniTransform, sitk.sitkNearestNeighbor, P_PostI.GetPixelID())
        P_PostM = sitk.Resample(P_PostM, P_PreM, IniTransform, sitk.sitkNearestNeighbor, P_PostM.GetPixelID())
        PostI = sitk.Resample(PostI, PreI, IniTransform, sitk.sitkNearestNeighbor, PostI.GetPixelID())

        # Extract slices for quick registration
        Time.Update(5/9, 'Estimate start')
        PreS = GetSlice(P_PreM, int(P_PreM.GetSize()[2]*0.8))
        PostS = GetSlice(P_PostM, int(P_PostM.GetSize()[2]*0.8))

        # Binary dilation for easier registration
        PreS = sitk.BinaryDilate(PreS, 5)
        PostS = sitk.BinaryDilate(PostS, 5)

        # Set rotations variables
        NRotations = 8
        Angle = 2*sp.pi/NRotations
        Rotation2D = sitk.Euler2DTransform()
        PhysicalSize = np.array(P_PostM.GetSize()) * np.array(P_PostM.GetSpacing())
        Center = (PhysicalSize + np.array(P_PostM.GetOrigin())) / 2
        Rotation2D.SetCenter(Center[:2])

        # Find best image initial position with successive rotations
        Measure = sitk.LabelOverlapMeasuresImageFilter()
        Dices = pd.DataFrame()
        for i in range(NRotations):

            # Set initial rotation
            M = RotationMatrix(Alpha=0, Beta=0, Gamma=i*Angle)
            Rotation2D.SetMatrix([v for v in M[:2,:2].flatten()])
            PostR = sitk.Resample(PostS, Rotation2D)

            # Register images
            Dict = {'MaximumNumberOfIterations': [256]}
            Result, TPM = Registration.Register(PreS, PostR, 'rigid', Dictionary=Dict)
            Result = sitk.Cast(Result, PreS.GetPixelID())

            # Compute dice coefficient
            Measure.Execute(PreS, Result)
            Dice = Measure.GetDiceCoefficient()
            NewData = pd.DataFrame({'Angle':float(i*Angle/sp.pi*180), 'DSC':Dice}, index=[i])
            Dices = pd.concat([Dices, NewData])

            if Dice == Dices['DSC'].max():
                # Show.Slice(Moving_Bin)
                # Show.Overlay(PreS, Result, AsBinary=True)
                BestAngle = float(i*Angle)
                Parameters = np.array(TPM[0]['TransformParameters'], 'float')

        # Apply best rotation
        T = sitk.Euler3DTransform()
        R = RotationMatrix(Gamma=BestAngle + Parameters[0])
        T.SetMatrix([Value for Value in R.flatten()])
        T.SetTranslation((Parameters[0], Parameters[1], 0))
        T.SetCenter(Center)

        P_PostI = sitk.Resample(P_PostI, T)
        PostI = sitk.Resample(PostI, T)

        # Perform rigid registration and transform mask
        Time.Update(6/9, 'Rigid Reg.')
        RigidI, TPM = Registration.Register(P_PreI, P_PostI, 'rigid',  Path=str(ResultsDir))
        TPM[0]['Size'] = [str(S) for S in PreI.GetSize()]
        TPM[0]['Spacing'] = [str(S) for S in PreI.GetSpacing()]
        TPM[0]['Origin'] = [str(O) for O in PreI.GetOrigin()]
        RigidP = Registration.Apply(PostI, TPM)

        Show.FName = str(ResultsDir / 'RigidRegistration.png')
        Show.Overlay(PreI, RigidP, Axis='X', AsBinary=True)
        
        NFile = str(ResultsDir / 'Rigid')
        Write.MHD(RigidP, NFile, PixelType='float')

        # Perform bspline registration
        if Arguments.Type == 'BSpline':
            Time.Update(7/9, 'B-Spline Reg.')

            ## Specific parameters
            Schedule = np.repeat([32, 16, 8, 4, 2],3)
            Dictionary = {'FixedImagePyramidSchedule':Schedule,
                        'MovingImagePyramidSchedule':Schedule,
                        'NewSamplesEveryIteration':['true'],
                        'SP_a':['1']}

            ## Match b-spline interpolation with elements size
            hFE = sitk.ReadImage(str(Results / '03_hFE' / Arguments.Sample / 'J.mhd'))
            Dictionary['FinalGridSpacingInPhysicalUnits'] = [str(v) for v in hFE.GetSpacing()]
            Dictionary['NumberOfResolutions'] = ['5']
            Dictionary['GridSpacingSchedule'] = ['16', '8', '4', '2', '1']

            ## Perform b-spline registration
            BSplineI, TPM = Registration.Register(P_PreI, RigidI, 'bspline', Dictionary=Dictionary)
            TPM[0]['Size'] = [str(S) for S in PreI.GetSize()]
            TPM[0]['Spacing'] = [str(S) for S in PreI.GetSpacing()]
            TPM[0]['Origin'] = [str(O) for O in PreI.GetOrigin()]
            BSplineP = Registration.Apply(RigidP, TPM)
            NFile = str(ResultsDir / 'NonRigid')
            Write.MHD(BSplineP, NFile, PixelType='float')
            
            Show.FName = str(ResultsDir / 'BSplineRegistration')
            Show.Overlay(PreI, BSplineP, AsBinary=True, Axis='X')


        # Compute deformation jacobian
        if Arguments.Jac == True:
            Time.Update(8/9, 'Compute Jac.')

            ## Resample mask to match hFE element size and apply transform to compute jacobian
            RigidR = Resample(RigidP, Spacing=hFE.GetSpacing())
            TPM[0]['Size'] = [str(S) for S in hFE.GetSize()]
            TPM[0]['Spacing'] = [str(S) for S in hFE.GetSpacing()]
            BSplineR = Registration.Apply(RigidR, TPM, str(ResultsDir), Jacobian=True)

            ## Read Jacobian
            JacobianFile = str(ResultsDir / 'fullSpatialJacobian.nii')
            JacobianImage = sitk.ReadImage(JacobianFile)
            JacobianImage.SetSpacing(hFE.GetSpacing())

            ## Perform jacobian unimodular decomposition
            SphericalCompression, IsovolumicDeformation = DecomposeJacobian(JacobianImage)
            
            ## Write results
            JFile = str(ResultsDir / 'J')
            FFile = str(ResultsDir / 'F_Tilde')
            Write.MHD(SphericalCompression, JFile, PixelType='float')
            Write.MHD(IsovolumicDeformation, FFile, PixelType='float')

        Time.Process(0, Sample)

    return

#%% Execution part
# Execution as main
if __name__ == '__main__':

    # Initiate the parser with a description
    FC = argparse.RawDescriptionHelpFormatter
    Parser = argparse.ArgumentParser(description=Description, formatter_class=FC)

    # Add long and short argument
    SV = Parser.prog + ' version ' + Version
    Parser.add_argument('-V', '--Version', help='Show script version', action='version', version=SV)
    Parser.add_argument('Sample', help='Sample number (required)', type=str)

    # Add defaults arguments
    Parser.add_argument('-F', '--Folder', help='Root folder name', type=str, default='FRACTIB')
    Parser.add_argument('-T','--Type', help='Registration type', type=str, default='Rigid')
    Parser.add_argument('-S','--Show', help='Show plots', type=bool, default=False)
    Parser.add_argument('-J','--Jac', help='Compute deformation Jacobian', type=bool, default=False)

    # Read arguments from the command line
    Arguments = Parser.parse_args()

    Main(Arguments)