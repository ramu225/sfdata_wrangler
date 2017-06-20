
# allows python3 style print function
from __future__ import print_function


# -*- coding: utf-8 -*-
__author__      = "Gregory D. Erhardt"
__copyright__   = "Copyright 2013 SFCTA"
__license__     = """
    This file is part of sfdata_wrangler.

    sfdata_wrangler is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    sfdata_wrangler is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with sfdata_wrangler.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys
import numpy as np
import datetime
from mm.path_inference.structures import StateCollection, Position
from mm.path_inference.learning_traj import LearningTrajectory
from mm.path_inference.learning_traj_viterbi import TrajectoryViterbi1
from mm.path_inference.learning_traj_smoother import TrajectorySmoother1

    


def point_feature_vector(sc):
    """ The feature vector of a point.

    This is used as a scoring function, where each possible state is given
    a score based on the distance from that state to the recorded GPS
    position.  It is a maximization problem, so the score must be negative. 
         
    It returns an array with two elements, the first element being the
    pathscore and the second being the pointscore.  Since this is for points, 
    the pathscore is always zero.  There is one element for each state 
    in the state collection
                
    The pointscore is based on the distance from the candidate state to the 
    recorded GPS position. 

    """
    point_features = []
    for s in sc.states:
        score = [0, -s.distFromGPS]
        point_features.append(score)
    return point_features
    
    

def path_feature_vector(hwynet, path, tt):
    """ The feature vector of a path.

    This is used as a scoring function, where the path is given a score
    based on the square of the difference in travel time calculated from 
    the links versus between the GPS recordings. It is a maximization problem, 
    so the score must be negative. 
         
    It returns an array with two elements, the first element being the
    pathscore and the second being the pointscore.  Since this is for paths, 
    the pointscore is always zero.  
         
    Here, the scoring is based on the free flow travel time and a penalty for 
    free flow travel time in excess of what is observed.  In this
    way, we double-penalize paths that look too long, getting shorter paths. 

    """  
    
    if (path==None or len(path.links)==0):
        return [-sys.maxsize, 0]
        
    else: 
        path_tt = hwynet.getPathFreeFlowTTInSecondsWithTurnPenalties(path)
        score = -1.0 * (path_tt + 1.0*max(path_tt - tt, 0))        
        return [score, 0]
    

class Trajectory():
    """ 
    Class to represent a vehicle trajectory through a network. 
    """

    # THETA is a way to weight the relative value given to the 
    # path score versus the point score when selecting the most
    # likely trajectory.  Its format is n.parray([pathweight, pointweight])
    # These weights can be tuned to achieve good results. 
    THETA = np.array([1.0, 0.5])
    
    
    def __init__(self, hwynet, df):
        """
        Constructor. 
        hwynet - a HwyNetwork for projecting and building paths
        df - a dataframe with GPS points for this trajectory  
        """   
        
        # there is one point for each GPS observations
        # the states are collection of possible locations in the network
        self.candidatePoints = []                

        # there is one set of paths betweeen each pair of GPS observations
        # for each, there is a collection of possible paths
        self.candidatePaths = []

        # the observed travel times corresponding to these paths
        self.traveltimes = []
        
        # features is a scoring method for each candidate point or path
        #
        # point_feature_vector contains [pathscore, pointscore] for each 
        # candidate state.  
        # 
        # path_feature_vector contains [pathscore, pointscore] for each 
        # candidate path. 
        # 
        # In total, the features are an alternating sequence of points and paths, 
        # starting and ending with points. 
        self.features = []

        # The transitions go between each element (point or path) in the trajectory, 
        # so there are len(features) - 1 transitions.  
        # For points, a transition is (index of candidate state, index of candidate path)
        # For paths, a transition is (index of candidate path, index of candidate state)
        self.transitions = []
           
        # The indexes of the most likely elements of the trajectory
        # Point indexes and path indexes are interleaved.
        self.most_likely_indices = None


        # STEP 1: Create the points
        firstRow = True
        for i, row in df.iterrows():
            position = Position(row['x'], row['y'])         
            states = hwynet.project(position)
            
            # if point is not near any links, just skip this point
            if (len(states)==0):
                continue
            
            sc = StateCollection(row['cab_id'], states, position, row['time'])
            self.candidatePoints.append(sc)
            
            # travel times between the points
            if (not firstRow): 
                self.traveltimes.append(row['seconds'])
            firstRow = False
            
        # STEP 2: Check that we're not dealing with an emtpy set
        if (len(self.candidatePoints)==0):
            return
                
        # STEP 3: Create the candidate paths between each point
        #         and fill up the features while we're at it
        point_scores = point_feature_vector(self.candidatePoints[0]) 
        self.features.append(point_scores)
        
        for i in range(1, len(self.candidatePoints)):
            (trans1, ps, trans2) = \
                hwynet.getPathsBetweenCollections(self.candidatePoints[i-1], self.candidatePoints[i])
            
            # transitions and paths
            self.transitions.append(trans1)
            self.candidatePaths.append(ps)
            self.transitions.append(trans2)
            
            # features are used for scoring
            paths_features = []
            for path_ in ps:
                path_scores = path_feature_vector(hwynet, path_, self.traveltimes[i-1])
                paths_features.append(path_scores)
            self.features.append(paths_features)
            
            point_scores = point_feature_vector(self.candidatePoints[i])
            self.features.append(point_scores)
        

    def calculateMostLikely(self):
        """ Calculates the indices of the most likely trajectory.
        
        The result alternates between point indices and path indices
        and correspond to the candidate points and candidate paths. 
        """
        
        # a LearningTrajectory is the basic data structure that stores the 
        # features (scores candidate states candidate paths), and transitions 
        # (indices to look up those states or paths). 
        traj = LearningTrajectory(self.features, self.transitions)

        # The viterbi is a specific algorithm that calculates the most likely
        # states and most likley paths.  The key output are the indices noted 
        # below, which can be used to look up the specific candidate states
        # and candidate paths (although those must be stored externally.  
        # There is one index for each feature. 
        viterbi = TrajectoryViterbi1(traj, self.THETA)
        try: 
            viterbi.computeAssignments()
        except (ValueError):
            for f in self.features:
                print (f)
            for t in self.transitions:
                print (t)
            print (self.THETA)
            raise 

        # The indexes of the most likely elements of the trajectory
        # Point indexes and path indexes are interleaved.
        self.most_likely_indices = viterbi.assignments
    

    def calculateProbabilities(self):
        """ Calculates the probabilities for all possible options.
        
        The result alternates between point indices and path indices
        and correspond to the candidate points and candidate paths. 
        
        Returns the probabilities. 
        """
        
        # The smoother is a different algorithm that gives probabilities instead
        # of the most likley.  
        traj = LearningTrajectory(self.features, self.transitions)
        smoother = TrajectorySmoother1(traj, self.THETA)
        smoother.computeProbabilities()
        return smoother.probabilities


    def getMostLikelyPaths(self):
        """ Returns an array of the most likely paths to be traversed.  
                
        """
        
        if self.most_likely_indices == None:
            raise RuntimeError('Need to calculate most likely indices!')         
        
        elements = []
        for i in range(0, len(self.most_likely_indices)):
            
            # it is only a path if i is odd, otherwise its a state collection
            if ((i%2) == 1): 
                j = (i-1) // 2
                path = self.candidatePaths[j][self.most_likely_indices[i]]
                elements.append(path)
        
        return elements


    def getPathStartEndTimes(self):
        """ Returns the starting and ending times for each path
        in the trajectory.  
                
        """        
        times = []
        for i in range(1, len(self.candidatePoints)):
            startTime = self.candidatePoints[i-1].time
            endTime = self.candidatePoints[i].time
            times.append((startTime, endTime))
        
        return times


    def printDebugInfo(self, outstream, ids=None):
        """
        Prints details about the trajectory to the outfile.
        """
        
        # calculate the probabilities for this trajectory
        probabilities = self.calculateProbabilities()
                
        outstream.write('**************************************************************\n')
        outstream.write('Printing trajectory at ' + str(datetime.datetime.now().ctime()) + '.\n')
                
        # ids, if provited
        if (not (ids==None)): 
            (cab_id, trip_id) = ids
            outstream.write('cab_id =  ' + str(cab_id) + '\n')
            outstream.write('trip_id = ' + str(trip_id) + '\n')
        
        outstream.write('THETA = ' + str(self.THETA) + '\n\n')        

        
        i=0
        for (feature, most_likely, prob) in zip(
                self.features, self.most_likely_indices, probabilities):
                        
            # it is a state if i is even, and a path if i is odd
            if ((i%2) == 0): 
                elementType = 'state'
                j = i//2
                candidates = self.candidatePoints[j].states 
                attribute = self.candidatePoints[j].time 
            if ((i%2) == 1): 
                elementType = 'path'
                j = (i-1) // 2
                candidates = self.candidatePaths[j]
                attribute = self.traveltimes[j]

            # write the basic info
            outstream.write('  --------------------------------------------------------\n')
            outstream.write('  ELEMENT:   ' + str(i) +'\n')
            outstream.write('  Type:      ' + elementType + '\n')
            if (elementType=='state'):
                outstream.write('  Timestamp: ' + str(attribute) + '\n\n')
            else:
                outstream.write('  Travel Time: ' + str(attribute) + '\n\n')
            
            # write the details of each possible candidate
            k=0
            for (c, f, p) in zip(candidates, feature, prob):
                outstream.write('    CANDIDATE:   ' + str(k) + '\n')
                outstream.write('    candidate:   ' + str(c) + '\n')
                outstream.write('    feature:     ' + str(f) + '\n')
                outstream.write('    probability: ' + str(p) + '\n')
                if (k==most_likely): 
                    outstream.write('    MOST LIKELY!\n')
                outstream.write('\n')
                k+=1
            
            # increment the counter
            i+=1
            
        
        outstream.write('\n\n')
