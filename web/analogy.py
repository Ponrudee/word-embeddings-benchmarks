"""
 Classes and function for answering analogy questions
"""

import sys
import scipy
import logging
import pandas as pd
from collections import OrderedDict
logger = logging.getLogger('')
import sklearn
from .datasets.analogy import *
from itertools import *
from .utils import batched




class SimpleAnalogySolver(sklearn.base.BaseEstimator):
    """
    Answer analogy questions

    Parameters
    ----------
    w : Embedding instance

    method : {"add", "mul"}
      Method to use when finding analogy answer, see "Improving Distributional Similarity
      with Lessons Learned from Word Embeddings" O. Levy et al. 2014.

    batch_size : int
      Batch size to use while computing accuracy. This is because of extensive memory usage.

    k: int
      If not None will select k top most frequent words from embedding

    Note
    ----
    It is suggested to normalize and standardize embedding before passing it to SimpleAnalogySolver
    Because of memory constraints, SimpleAnalogySolver **is not making a copy** of passed embeddings
    """

    def __init__(self, w, method="add", batch_size=300, k=None):
        self.w = w
        self.batch_size = batch_size
        self.method = method
        self.k = k

    def score(self, X, y):
        """
        Calculate accuracy on analogy questions dataset

        Parameters
        ----------
        X : array-like, shape (n_samples, 3)
          Analogy questions.

        y : array-like, shape (n_samples, )
          Analogy answers.

        Returns
        -------
        acc : float
          Accuracy
        """
        return np.mean(y == self.predict(X))

    # TODO: rewrite for mlp!
    def predict(self, X):
        """
        Answer analogy questions

        Parameters
        ----------
        X : array-like, shape (n_samples, 3)
          Analogy questions.

        Returns
        -------
        y_pred : array-like, shape (n_samples, )
          Predicted words.
        """
        w = self.w.most_frequent(self.k) if self.k else self.w
        words = self.w.vocabulary.words
        mean_vector = np.mean(w.vectors, axis=0)
        output = []
        # Batch due to memory constaints (in dot operation)
        for id_batch, batch in enumerate(batched(xrange(len(X)), self.batch_size)):
            ids = list(batch)
            X_b = X[ids]
            if id_batch % np.floor(len(X)/(10. * self.batch_size)) == 0:
                logger.info("Processing {}/{} batch".format(int(np.ceil(ids[1] / float(self.batch_size))),
                                                            int(np.ceil(X.shape[0] / float(self.batch_size)))))

            A, B, C = np.vstack(w.get(word, mean_vector) for word in X_b[:, 0]), \
                      np.vstack(w.get(word, mean_vector) for word in X_b[:, 1]), \
                      np.vstack(w.get(word, mean_vector) for word in X_b[:, 2])

            if self.method == "add":
                D = np.dot(w.vectors, (B - A + C).T)
            elif self.method == "mul":
                D_A = np.log((1.0 + np.dot(w.vectors, A.T)) / 2.0 + 1e-5)
                D_B = np.log((1.0 + np.dot(w.vectors, B.T)) / 2.0 + 1e-5)
                D_C = np.log((1.0 + np.dot(w.vectors, C.T)) / 2.0 + 1e-5)
                D = D_B - D_A + D_C
            else:
                raise RuntimeError("Unrecognized method parameter")

            # Remove words that were originally in the query
            for id, row in enumerate(X_b):
                D[[w.vocabulary.word_id[r] for r in row if r in
                   w.vocabulary.word_id], id] = np.finfo(np.float32).min

            output.append([words[id] for id in D.argmax(axis=0)])

        return np.array([item for sublist in output for item in sublist])


def evaluate_on_semeval_2012_2(w):
    """
    Simple method to score embedding using SimpleAnalogySolver

    Parameters
    ----------
    w : Embedding instance

    Returns
    -------
    result: pandas.DataFrame
      Results with spearman correlation per broad category with special key "all" for summary
      spearman correlation
    """
    data = fetch_semeval_2012_2()
    mean_vector = np.mean(w.vectors, axis=0, keepdims=True)
    categories = data.y.keys()
    results = defaultdict(list)
    for c in categories:
        # Get mean of left and right vector
        prototypes = data.X_prot[c]
        prot_left = np.mean(np.vstack(w.get(word, mean_vector) for word in prototypes[:, 0]), axis=0)
        prot_right = np.mean(np.vstack(w.get(word, mean_vector) for word in prototypes[:, 1]), axis=0)

        questions = data.X[c]
        question_left, question_right = np.vstack(w.get(word, mean_vector) for word in questions[:, 0]), \
            np.vstack(w.get(word, mean_vector) for word in questions[:, 1])

        scores = np.dot(prot_left - prot_right, (question_left - question_right).T)

        c_name = data.categories_names[c].split("_")[0]
        # NaN happens when there are only 0s, which might happen for very rare words or
        # very insufficient word vocabulary
        cor = scipy.stats.spearmanr(scores, data.y[c]).correlation
        results[c_name].append(0 if np.isnan(cor) else cor)

    final_results = OrderedDict()
    final_results['all'] = sum(sum(v) for v in results.values()) / len(categories)
    for k in results:
        final_results[k] = sum(results[k])/len(results[k])
    return pd.Series(final_results)

def evaluate_on_analogy(w, X, y, method="add", k=None, category=None, batch_size=100):
    """
    Simple method to score embedding using SimpleAnalogySolver

    Parameters
    ----------
    w : Embedding instance

    method : {"add", "mul"}
      Method to use when finding analogy answer, see "Improving Distributional Similarity
      with Lessons Learned from Word Embeddings"

    X : array-like, shape (n_samples, 3)
      Analogy questions.

    y : array-like, shape (n_samples, )
      Analogy answers.

    k : int, default: None
      If not None will select k top most frequent words from embedding

    batch_size : int, default: 100
      Increase to increase memory consumption and decrease running time

    category : list, default: None
      Category of each example. Will calculate accuracy per category as well

    Returns
    -------
    result: dict
      Results, where each key is for given category and special empty key "" stores
      summarized accuracy across categories
    """

    assert category is None or len(category) == y.shape[0], "Passed incorrect category list"


    solver = SimpleAnalogySolver(w=w, method=method, batch_size=batch_size, k=k)
    y_pred = solver.predict(X)

    if category is not None:
        results = OrderedDict({"all": np.mean(y_pred == y)})
        for cat in set(category):
            results[cat] = np.mean(y_pred[category==cat] == y[category==cat])

        return pd.Series(results)
    else:
        return np.mean(y_pred == y)