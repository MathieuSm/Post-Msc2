#%% #!/usr/bin/env python3
# Initialization

Version = '01'

Description = """
    Analysis of the morphometric measurements

    Version Control:
        01 - Original script

    Author: Mathieu Simon
            ARTORG Center for Biomedical Engineering Research
            SITEM Insel, University of Bern

    Date: April 2023
    """

#%% Imports
# Modules import

import os
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
import SimpleITK as sitk
import matplotlib.pyplot as plt
from Utils import SetDirectories, Show, Read, Time

Read.Echo = False

#%% Functions
# Define functions

def AFunction(Argument):

    return 

#%% Main
# Main code

def Main():

    # Read data
    WD, DD, SD, RD = SetDirectories('FRACTIB')
    Data = pd.read_csv(str(RD / 'Morphometry.csv'))
    # Check = pd.read_csv(str(RD / '01_Morphology' / '00_Data.csv'))
    # Map = pd.read_csv(str(DD / 'SampleList.csv'))
    # Sort = Map['MicroCT pretest file number'].argsort().sort_values().index
    Structural = pd.read_csv(str(RD / 'Structural.csv'), header=[0,1])

    # print(Check.mean(numeric_only=True))
    print(Data.mean(numeric_only=True))
    print(Data.std(numeric_only=True))

    OLS = Show.OLS(Data['BV/TV (-)'], Structural['Experiment']['Stiffness (N/mm)']/1E3)
    # OLS = Show.OLS(Check.loc[Sort, 'BV/TV'], Structural['Experiment']['Stiffness (N/mm)']/1E3)

    OLS1 = Show.OLS(Data['BMC (mgHA)']/1E3, 
                    Structural['Experiment']['Stiffness (N/mm)']/1E3,
                    Labels=['BMC (gHA)', 'Experimental Stiffness (kN/mm)'],
                    Annotate=['R2'])
    OLS2 = Show.OLS(Data['BMC (mgHA)']/1E3,
                    Structural['Experiment']['Ultimate Load (N)']/1E3,
                    Labels=['BMC (gHA)', 'Experimental Ultimate Load (kN)'],
                    Annotate=['R2'])

    # Compute apparent properties
    Columns = ['Height (mm)', 'Mean Area (mm2)']
    AppProps = pd.DataFrame(index=Data['Internal ID'], columns=Columns)
    
    for Index, Row in Data.iterrows():

        Time.Process(1, Row['Internal ID'])
        AppProps.loc[Row['Internal ID'], 'Stiffness (N/mm)'] = Structural.loc[Index, 'Experiment']['Stiffness (N/mm)']
        AppProps.loc[Row['Internal ID'], 'Max Force (N)'] = Structural.loc[Index, 'Experiment']['Max Force (N)']

        ImagesDir = DD / '02_uCT' / Row['Internal ID']
        Images = [I for I in os.listdir(ImagesDir) if I.endswith('TRAB_MASK.AIM')]
        Images.sort()

        Time.Update(1/10,'Read AIMs')
        Trab = Read.AIM(str(ImagesDir / Images[0]))[0]
        Cort = Read.AIM(str(ImagesDir / Images[0].replace('TRAB','CORT')))[0]
        Mask = sitk.GetArrayFromImage(Trab + Cort)
        Mask[Mask > 0] = 1

        Image = Read.AIM(str(ImagesDir / Images[0].replace('_TRAB_MASK','')))[0]
        Spacing = np.round(Image.GetSpacing(), 6)

        Time.Update(5/10,'Compute Area')
        Height = 0
        Volume = 0
        for iS, Slice in enumerate(Mask):
            Area = Slice.sum()
            if Area > 0:
                Volume += Area * np.prod(Spacing)
                Height += Spacing[2]
            
            Time.Update((5 + iS/Mask.shape[0] * 5)/10)
        
        AppProps.loc[Row['Internal ID'], Columns[0]] = Height
        AppProps.loc[Row['Internal ID'], Columns[1]] = Volume / Height

        Time.Process(0, Row['Internal ID'])

    AppProps['Apparent Modulus (N/mm2)'] = AppProps['Stiffness (N/mm)'] * AppProps[Columns[0]] / AppProps[Columns[1]]
    AppProps['Apparent Strength (N/mm2)'] = AppProps['Max Force (N)'] / AppProps[Columns[1]]
    del AppProps['Stiffness (N/mm)']
    del AppProps['Max Force (N)']
    AppProps.to_csv(str(RD / 'ApparentProps.csv'))

    OLS3 = Show.OLS(Data['vBMD (mgHA/cm3)'],
                    np.array(AppProps['Apparent Modulus (N/mm2)']/1E3, float),
                    Labels=['vBMD (mgHA/cm3)', 'Apparent Modulus (kN/mm$^2$)'],
                    Annotate=['R2'])
    OLS4 = Show.OLS(Data['vBMD (mgHA/cm3)'],
                    np.array(AppProps['Apparent Strength (N/mm2)'], float),
                    Labels=['vBMD (mgHA/cm3)', 'Apparent Strength (N/mm$^2$)'],
                    Annotate=['R2'])
    
    Residuals = pd.DataFrame()
    Residuals['Experimental Stiffness'] = OLS1.resid
    Residuals['Experimental Ultimate Load'] = OLS2.resid
    Residuals['Apparent Modulus'] = OLS3.resid
    Residuals['Apparent Strength'] = OLS4.resid
    Residuals.index = [S[:3] for S in Data['Internal ID']]

    Show.FName = str(RD / 'Residuals1.png')
    Show.BoxPlot([Residuals[C] / Residuals[C].abs().max() for C in Residuals.columns],
                 Labels=['', 'Normalized residuals (-)'], SetsLabels=['Stiffness','Ult. Load','Modulus','Strength'])
    Show.FName = None

    Colors = [(1,0,0), (0,0,1), (1,0,0), (0,0,1)]
    Shapes = ['o', 'o', 'x', 'x']
    Mew = [2,1,2,1]
    Figure, Axis = plt.subplots(1,1)
    for iC, C in enumerate(Residuals.columns):
        Axis.plot(Residuals.index, Residuals[C] / Residuals[C].abs().max(), label=C,
                  color=Colors[iC], marker=Shapes[iC], mew=Mew[iC], linestyle='none', fillstyle='none')
    Axis.set_xlabel('Sample (-)')
    Axis.set_ylabel('Normalized residuals (-)')
    Axis.set_xticklabels(Residuals.index, rotation=90)
    plt.legend(loc='upper center', bbox_to_anchor=[0.5, 1.2], ncol=2)
    plt.tight_layout()
    plt.savefig(str(RD / 'Residuals2.png'))
    plt.show()

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

    # Read arguments from the command line
    Arguments = Parser.parse_args()

    Main()