import numpy as np
import pandas as pd
import networkx as nx
from sklearn.metrics.pairwise import pairwise_distances, cosine_similarity
from sklearn.preprocessing import minmax_scale
import warnings
warnings.filterwarnings('ignore')

class ddc_outlier():
    y_pred = []
    pr = {}
    frequency = pd.DataFrame([])
    alpha = 0.5
    metric = 'similarity'
    sim_matrix = np.zeros((1,1))

    def __init__(self, alpha=0.5, metric='similarity'):
        self.alpha = alpha
        self.metric = metric
    
    def fit(self, X):
        self.frequency = X
        X = self.frequency[['dose','frequency']].values.astype(float)
        try:
            if self.metric == 'similarity':
                self.sim_matrix = cosine_similarity(X,X)
            else:
                self.sim_matrix = pairwise_distances(X,X,self.metric)
            medication_graph = nx.from_numpy_array(self.sim_matrix)
            self.pr = nx.pagerank(medication_graph, alpha=0.9, max_iter=1000, personalization=dict(self.frequency['count']))
        except:
            self.pr = dict(enumerate(np.zeros((len(X),1)).flatten()))
    
    def get_params(self):
        return self.pr, self.sim_matrix
    
    def predict(self, X):
        medication = X
        medication['pr'] = 0

        for idx_frequency in self.frequency.index:
            med_frequency = self.frequency.iloc[idx_frequency]
            medication_index = medication[
                                        (medication['dose'] == med_frequency['dose']) &
                                        (medication['frequency'] == med_frequency['frequency'])
                                        ].index
            if len(medication_index) > 0:
                medication.loc[medication_index,'pr'] = self.pr[idx_frequency]
        
        pr_threshold = np.mean(np.array(list(self.pr.values())))

        y_pred = medication['pr'].values
        y_pred[y_pred < (pr_threshold*self.alpha)] = -1 # flag overdose
        y_pred[y_pred >= (pr_threshold*self.alpha)] = 1 # convert to false
        return y_pred
    
def minMaxScale(scores):
    pr_threshold = np.mean(scores)
    a = (scores / pr_threshold)
    b = np.where(a < 1, a, 1)
    return np.abs(np.round(minmax_scale(b, feature_range=(0,3)) - 3))

def build_model(selected, metric='jaccard'):
    if len(selected) == 0: 
        print('No prescriptions')
        return 0

    X = selected[['dose','frequency','count']].reset_index()

    # compute scores
    ddc_j = ddc_outlier(alpha=1, metric=metric)
    ddc_j.fit(X)
    selected['outlier_jaccard'] = ddc_j.predict(X)
    scores_mean_j = minMaxScale(list(ddc_j.pr.values()))

    # propagate scores
    for i, f in enumerate(ddc_j.frequency.values):
        med_indexes = selected[(selected['dose']==f[1]) & (selected['frequency']==f[2])].index
        selected.loc[med_indexes, 'score'] = scores_mean_j[i]

    return selected

def add_score(drugsItem):
   
    columns = ['medication', 'frequency', 'dose', 'count', 'score']
    models = pd.DataFrame(columns=columns)

    result = build_model(drugsItem)
    selected = result[columns].groupby(columns).count().reset_index()
    models = models.append(selected)

    return models