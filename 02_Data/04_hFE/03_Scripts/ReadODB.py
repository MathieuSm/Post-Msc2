# ReadODB.py
# A script to read deformation gradient from odb file from ABAQUS.

from odbAccess import *
import numpy as np
import csv

print '\n\n\n'
print 'Open odb file...'
odb = openOdb(path='/home/ms20s284/FRACTIB/2_FEA/432_L_77_F/Test.odb')

# Create a variable that refers to the
# last frame of the first step.

LastFrame = odb.steps['Step-1'].frames[-1]

# Create a variable that refers to the displacement 'U'
# in the last frame of the first step.

F11 = LastFrame.fieldOutputs['SDV_F11']
F12 = LastFrame.fieldOutputs['SDV_F12']
F13 = LastFrame.fieldOutputs['SDV_F13']
F21 = LastFrame.fieldOutputs['SDV_F21']
F22 = LastFrame.fieldOutputs['SDV_F22']
F23 = LastFrame.fieldOutputs['SDV_F23']
F31 = LastFrame.fieldOutputs['SDV_F31']
F32 = LastFrame.fieldOutputs['SDV_F32']
F33 = LastFrame.fieldOutputs['SDV_F33']

F = [F11,F12,F13,F21,F22,F23,F31,F32,F33]
F_Names = ['F11','F12','F13','F21','F22','F23','F31','F32','F33']

Instance = odb.rootAssembly.instances['PART-1-1']
Nodes = Instance.nodes

# Create node labels array
NodeLabels = np.array([])
for Node in Nodes:
    NodeLabels = np.append(NodeLabels,Node.label)

# Initialize loop
N = len(Instance.elements)
ElementsPositions = np.zeros((3,N))
DeformationGradients = np.zeros((9,N))
ElementNumber = 0

print '\n\n\n'
print 'Read elements data...'
for Element in Instance.elements[:N]:
    #print '\n'
    #print 'Element label: ', Element.label
    #print 'Element connectivity: ', Element.connectivity
    
    # Compute element central position
    XYZ = np.zeros((len(Element.connectivity),3))
    NodeNumber = 0
    for NodeLabel in Element.connectivity:
        #print '\n'
        #print 'Node label: ', NodeLabel
        Node = np.where(NodeLabels==NodeLabel)[0][0]
        #print 'Node coordinates: ', Nodes[Node].coordinates
        for Axis in range(3):
            XYZ[NodeNumber,Axis] = Nodes[Node].coordinates[Axis]
        NodeNumber += 1
        
    # Get element mean deformation gradient
    F_IntegrationPoints = np.zeros((1,9))
    
    for F_Component in range(9):
        F_Value = F[F_Component].getSubset(region=Element).values[0].data
        #print F_Names[F_Component], ': ', F_Value
        F_IntegrationPoints[0,F_Component] = F_Value
        
    # Add data to arrays and increment
    ElementsPositions[:,ElementNumber] = np.mean(XYZ,axis=0)
    DeformationGradients[:,ElementNumber] = F_IntegrationPoints
    
    ElementNumber += 1
    

# Write into csv file
print '\n\n\n'
print 'Save to csv...'
with open('ElementsPositions.csv', 'w') as File:
    Writer = csv.writer(File)
    for Row in ElementsPositions.T:
        Writer.writerow(Row)
        
with open('DeformationGradients.csv', 'w') as File:
    Writer = csv.writer(File)
    for Row in DeformationGradients.T:
        Writer.writerow(Row)
        
        

odb.close()
