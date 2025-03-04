# ======================================================================================================================
#
#                  ___                                    ___          ___          ___                   ___
#       ___       /  /\                                  /  /\        /  /\        /  /\         ___     /  /\
#      /  /\     /  /::\                                /  /:/_      /  /::\      /  /::\       /  /\   /  /:/_
#     /  /:/    /  /:/\:\   ___     ___  ___     ___   /  /:/ /\    /  /:/\:\    /  /:/\:\     /  /:/  /  /:/ /\
#    /  /:/    /  /:/~/::\ /__/\   /  /\/__/\   /  /\ /  /:/ /::\  /  /:/  \:\  /  /:/~/:/    /  /:/  /  /:/ /::\
#   /  /::\   /__/:/ /:/\:\\  \:\ /  /:/\  \:\ /  /://__/:/ /:/\:\/__/:/ \__\:\/__/:/ /:/___ /  /::\ /__/:/ /:/\:\
#  /__/:/\:\  \  \:\/:/__\/ \  \:\  /:/  \  \:\  /:/ \  \:\/:/~/:/\  \:\ /  /:/\  \:\/::::://__/:/\:\\  \:\/:/~/:/
#  \__\/  \:\  \  \::/       \  \:\/:/    \  \:\/:/   \  \::/ /:/  \  \:\  /:/  \  \::/~~~~ \__\/  \:\\  \::/ /:/
#       \  \:\  \  \:\        \  \::/      \  \::/     \__\/ /:/    \  \:\/:/    \  \:\          \  \:\\__\/ /:/
#        \__\/   \  \:\        \__\/        \__\/        /__/:/      \  \::/      \  \:\          \__\/  /__/:/
#                 \__\/                                  \__\/        \__\/        \__\/                 \__\/
#
#   Author: Allen Gu, Breon Schmidt
#   License: MIT
#
# ======================================================================================================================

""" --------------------------------------------------------------------------------------------------------------------
Imports
---------------------------------------------------------------------------------------------------------------------"""

''' External '''
import time
import joblib
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import sys
import gzip
import pickle
import csv
import os
import conorm


from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from joblib import Parallel, delayed, parallel_backend  

'''  Internal '''
from TALLSorts.common import message, root_dir, create_dir
from TALLSorts.user import UserInput
from TALLSorts.stages.subtype_class import SubtypeClass, reconstructSubtypeObj, genSubtypeObjsFromHierarchy, gen_hierarchy_dict
from TALLSorts.stages.scaling import scaleForTesting, createScaler
from TALLSorts.stages.classifier import Classifier
from TALLSorts.pipeline import TALLSorts

''' --------------------------------------------------------------------------------------------------------------------
Global Variables
---------------------------------------------------------------------------------------------------------------------'''

tallsorts_asci = """                                                            
   .--------. ,---.  ,--.   ,--.    ,---.                  ,--.         
   '--.  .--'/  O  \ |  |   |  |   '   .-'  ,---. ,--.--.,-'  '-. ,---. 
      |  |  |  .-.  ||  |   |  |   `.  `-. | .-. ||  .--''-.  .-'(  .-' 
      |  |  |  | |  ||  '--.|  '--..-'    |' '-' '|  |     |  |  .-'  `)
      `--'  `--' `--'`-----'`-----'`-----'  `---' `--'     `--'  `----' 
    """

''' --------------------------------------------------------------------------------------------------------------------
Functions
---------------------------------------------------------------------------------------------------------------------'''

def run(ui=False):
    """
    A function that outputs a set of predictions and visualisations as per an input set of samples.
    ...

    Parameters
    __________
    ui : User Input Class
        Carries all information required to execute TALLSorts, see UserInput class for further information.
    """

    if not ui:
        ui = UserInput()
        message(tallsorts_asci)

    # create output directory
    create_dir(ui.destination)

    # determining if we need to re-label gene labels
    if ui.gene_labels == 'symbol':
        ensembl_relabel = convert_symbols_to_ensembl(ui.samples.columns)
        ui.samples = ui.samples.drop(ensembl_relabel['unconfirmed'], axis=1)
        ui.samples.columns = [ensembl_relabel['confirmed'][i] for i in ui.samples.columns]

    # filling in NaN all columns
    ui.samples = ui.samples.fillna(0)

    if ui.mode == 'test':
        # run predictions
        tallsorts = load_classifier(ui.model_path) if ui.model_path else load_classifier()
        run_predictions(ui, tallsorts)
    elif ui.mode == 'train':
        # train classifier
        fit_classifier(ui, n_jobs=ui.training_cores)

def load_classifier(path=False):
    """
    Load the TALLSorts classifier from a pickled file.
    ...

    Parameters
    __________
    path : str
        Path to a pickle object that holds the TALLSorts model.
        Default: "/models/tallsorts/tallsorts.pkl.gz"

    Returns
    __________
    tallsorts : TALLSorts object
        TALLSorts object, unpacked, ready to go.
    """

    if not path:
        path = str(root_dir()) + "/models/tallsorts/tallsorts_default_model.pkl.gz"

    message("Loading classifier...")
    with gzip.open(path, 'rb') as f:
        tallsorts = pickle.load(f)
    return tallsorts

def run_predictions(ui, tallsorts):
    """
    Use TALLSorts to make predictions
    ...

    Parameters
    __________
    ui : User Input Class
        Carries all information required to execute TALLSorts, see UserInput class for further information.
    tallsorts : TALLSorts pipeline object

    Output
    __________
    Directories corresponding to hierarchy levels. Each directory contains:
        Probabilities.csv
        Predictions.csv
        Multi_calls.csv
        Distributions.png and html
        Waterfalls.png and html
        (at the ui.destination path)

    """

    # running the classifier
    results = tallsorts.predict(ui.samples)

    # writing the probabilities to a CSV
    for level in [level for level in results.levels if len(results.levels[level]) > 0]:
        level_cleaned = clean_label(level)
        create_dir(f'{ui.destination}/{level_cleaned}')
        results.levels[level]['probs_raw_df'].round(3).to_csv(f'{ui.destination}/{level_cleaned}/probabilities.csv', index_label='Sample')

        # writing the highest predictions to a CSV
        pred_csv = results.levels[level]['calls_df'][["y_pred"]].copy()
        pred_csv.columns = ["Predictions"]
        pred_csv.to_csv(f'{ui.destination}/{level_cleaned}/predictions.csv', index_label='Sample')

        # writing multi calls to a CSV
        sample_order = sorted(results.levels[level]['multi_calls'].keys(), key=lambda x: ui.samples.index.to_list().index(x))
        gen_multicall_csv(results.levels[level]['multi_calls'], sample_order, f'{ui.destination}/{level_cleaned}/multi_calls.csv')

        # if ui.counts: # currently not implemented
        #     message("Saving normalised/standardised counts.")
        #     processed_counts = results.transform(ui.samples)
        #     processed_counts["counts"].to_csv(f'{ui.destination}/{level_cleaned}/processed_counts.csv')

        get_figures(results_level=results.levels[level], 
                    destination=f'{ui.destination}/{level_cleaned}', 
                    label_list=get_children_of_label(tallsorts['clf'].subtypeObjects, level))
    
    message("Finished. Thanks for using TALLSorts!")
    sys.exit()

    # TALLSorts is in train mode
    

    message("Finished training. Thanks for using TALLSorts!")

"""
The following are functions used in the process of classifying objects
"""

def gen_multicall_csv(multi_calls, sample_order, path):
    if not multi_calls:
        return None
    max_multicall = max([len(multi_calls[i]) for i in multi_calls])
    with open(path, 'w') as f:
        csvwriter = csv.writer(f, delimiter=',')
        csvwriter.writerow(['']+[i for j in [[f'call_{k+1}', 'proba'] for k in range(max_multicall)] for i in j])
        for sample in sample_order:
            to_write = [sample]
            for call in multi_calls[sample]:
                to_write += [call[0], round(call[1],3)]
            to_write += ['' for i in range(2*max_multicall-len(to_write))]
            csvwriter.writerow(to_write)
    return None

def get_figures(results_level, destination, label_list, plots=["prob_scatter", "waterfalls"]):

    """
    Make figures of the results.
    ...

    Parameters
    __________
    samples : Pandas DataFrame
        Pandas DataFrame that represents the raw counts of your samples (rows) x genes (columns)).
    destination : str
        Location of where the results should be saved.
    probabilities : Pandas DataFrame
        The result of running the get_predictions(samples, labels=False, parents=False) function.
        See function for further usage.
    plots : List
        List of plots required. Default:  "distributions", "waterfalls", and "manifold".
        See https://github.com/Oshlack/AllSorts/ for examples.

    Output
    __________
    Distributions.png, Waterfalls.png, Manifold.png at the ui.destination path.

    """

    message("Saving figures...")

    for plot in plots:

        if plot == "prob_scatter":
            dist_plot = gen_sample_wise_prob_plot(results_level['probs_raw_df'], results_level['calls_df'], label_list, labelThreshDict=None, batch_name=None, figsize=(800,600), return_plot=True)
            dist_plot.write_image(destination + "/prob_scatters.png", scale=2, engine="kaleido")
            dist_plot.write_html(destination + "/prob_scatters.html")

        if plot == "waterfalls":
            waterfall_plot = gen_waterfall_distribution(results_level['calls_df'], label_list, labelThreshDict=None, batch_name=None, return_plot=True)
            waterfall_plot.write_image(destination + "/waterfalls.png", scale=2, engine="kaleido")
            waterfall_plot.write_html(destination + "/waterfalls.html")
        
def gen_sample_wise_prob_plot(probs_raw_df, calls_df, label_list, labelThreshDict=None, batch_name=None, figsize=(800,600), return_plot=False):
    """
    Given a set of predicted probabilities, generate a figure displaying distributions of probabilities. Analogous to `predict_dist` in ALLSorts.

    Essentially a visual representation of the probabilities.csv table.

    See https://github.com/Oshlack/TAllSorts/ for examples.
    ...

    Parameters
    __________
    probs_raw_df : Pandas DataFrame
        Table with samples (rows) and labels (columns). Entries are probabilities.
    calls_df : Pandas DataFrame
        A DataFrame with information about the top calls. Columns are: y_highest (highest call); proba_raw; proba_adj; y_pred (predicted call); multi_call (bool)
        Note that y_pred can be 'Unclassified', but y_highest will always be one of the labels.
    label_list: list
        List of labels
    labelThreshDict : dict
        Dict of thresholds with labels as keys and threshold as values. Currently not used.
    batch_name : str
        String name of the batch to include in the title of the plot
    figsize : tuple
        Tuple of width and height of final image
    return_plot : bool
        Rather than showing the plot through whatever IDE is being used, send it back to the function call.
        Likely so it can be saved.

    Returns
    __________
    Plotly object containing the drawn figure

    Output
    __________
    Probability distribution figure.

    """

    if labelThreshDict is None:
        labelThreshDict = {i:0.5 for i in label_list}

    jitter = 0.5
    n_samples = len(probs_raw_df.index)

    fig = go.Figure()

    for i in range(n_samples):
        sample = probs_raw_df.index[i]
        sample_row = probs_raw_df.loc[sample]
        x = list(range(len(sample_row.index)))
        y = sample_row.to_list()
        customdata = [[sample, i] for i in sample_row.index]
        fig.add_trace(go.Bar(x=x, y=y, width=0.9, 
                            marker={'color':'#90ee90'}, showlegend=False, visible=False,
                            customdata=customdata, hovertemplate='ID: %{customdata[0]}<br>%{customdata[1]}: %{y}<extra></extra>'))
    
    # add other points
    x = []
    y = []
    colour = []
    customdata = []
    for sample_no in range(n_samples):
        sample = probs_raw_df.index[sample_no]
        for label_no in range(len(label_list)):
            label_test = label_list[label_no]
            x.append(label_no + (np.random.random()-0.5)*jitter)
            y.append(probs_raw_df.loc[sample][label_test])
            colour.append('black')
            if calls_df.loc[sample]['y_pred'] in label_list:
                customdata.append([f'ID: {sample}<br>Call: {calls_df.loc[sample]["y_pred"]}<extra></extra>'])
            else:
                customdata.append([f'ID: {sample}<br>Call: {calls_df.loc[sample]["y_pred"]}<br>Highest: {calls_df.loc[sample]["y_highest"]}<extra></extra>'])

    fig.add_trace(go.Scatter(x=x, y=y,  mode="markers", marker={'color':colour, 'size':4}, visible=True, showlegend=False,
                            customdata=customdata, hovertemplate='%{customdata[0]}<extra></extra>'))

    # add threshold lines
    for x in range(len(label_list)):
            fig.add_shape(type="line",
                        x0=x-0.4, y0=labelThreshDict[label_list[x]],
                        x1=x+0.4, y1=labelThreshDict[label_list[x]],
                        line=dict(color="black", width=2), visible=True)

    # add dropdown
    fig.update_layout(
        updatemenus=[{
            'active':0,
            'buttons': [{'args':[{'visible':[False for j in range(n_samples)] + [True]}], 'label':'None', 'method':'update'}]
                    +[{'args':[{'visible':[j == i for j in range(n_samples)] + [True]}], 'label':probs_raw_df.index[i], 'method':'update'} for i in range(n_samples)],
            'direction':'down',
            'pad':{"r": 10, "t": 10},
            'showactive':True,
            'x':1, 'xanchor':"left",
            'y':0.8, 'yanchor':"top"
        }],
    )

    # adding dropdown text
    fig.update_layout(
        annotations=[{'text':"Select sample:", 'showarrow':False, 'x':1, 'xref':'paper', 'xanchor':"left", 'y':0.8, 'align':'left'}]
    )

    ticktext = label_list.copy()
    tickvals = [i for i in range(len(ticktext))]
    fig.update_xaxes(title_text='Classifier', showgrid=False, zeroline=False, 
                    tickmode = 'array', tickvals = tickvals, ticktext = ticktext, tickangle=45)
    fig.update_yaxes(title_text='Probability', range = (-0.01,1.01))
    fig.update_layout(title_text=f'Sample-wise classifier probabilities'+ (f': {batch_name} ({n_samples} samples)' if batch_name is not None else ''),
                    width=figsize[0],
                    height=figsize[1],
                    autosize=False,
                    template="plotly_white",
    )

    if return_plot:
        return fig
    else:
        fig.show()

def gen_waterfall_distribution(calls_df, label_list, labelThreshDict=None, batch_name=None, figsize=(1200,600), return_plot=False):

    """
    Given a set of predicted probabilities, generate a figure displaying the decreasing probabilities per sample. Analagous to `predict_waterfalls` and `_plot_waterfall` in ALLSorts

    This depiction is useful to compare probabilities more directly, in an ordered way, as to judge the efficacy of the classification attempt.

    See https://github.com/Oshlack/TAllSorts/ for examples.

    ...

    Parameters
    __________
    See descriptions in the gen_sample_wise_prob_plot function.

    Returns
    __________
    Plotly object containing the drawn figure

    Output
    __________
    Waterfalls figure.

    """

    if labelThreshDict is None:
        labelThreshDict = {i:0.5 for i in label_list}

    label_list_unclassified = label_list + ['Unclassified']
    label_colours = get_colours_for_labels(label_list_unclassified)

    waterfallDf = calls_df.copy()
    waterfallDf.sort_values('proba_adj', inplace=True, ascending=False)
    waterfallDf.sort_values('y_pred', inplace=True, kind='stable', key=lambda x: pd.Series([label_list_unclassified.index(y) for y in x]))
    waterfallDf['colour'] = waterfallDf['y_pred'].apply(lambda x:label_colours[x])
    waterfallDf['sample_id'] = waterfallDf.index
    fig = go.Figure()

    x = 0
    for sample in waterfallDf.index:
        sample_row = waterfallDf.loc[sample]
        if sample_row["y_pred"] == 'Unclassified':
            hovertemplate = f'ID: {sample}<br>Call: {sample_row["y_pred"]}<br>Highest call: {sample_row["y_highest"]}<extra></extra>'
        else:
            hovertemplate = f'ID: {sample}<br>Call: {sample_row["y_pred"]}<extra></extra>'
        fig.add_trace(go.Bar(x=[x], y=[sample_row['proba_raw']], width=0.9, 
                            marker={'color':sample_row['colour']}, showlegend=False,
                            hovertemplate=hovertemplate))
        if sample_row['y_pred'] in label_list:
            fig.add_shape(type="line",
                        x0=x-0.4, y0=labelThreshDict[sample_row['y_pred']],
                        x1=x+0.4, y1=labelThreshDict[sample_row['y_pred']],
                        line=dict(color="black", width=2))
        x += 1

    # custom legend
    for label in sorted(label_colours.keys(), key=lambda x:label_list_unclassified.index(x)):
        fig.add_trace(go.Bar(x=[None], y=[None], marker={'color':label_colours[label]}, showlegend=True, name=label))
    
    fig.update_xaxes(title_text='Samples', showgrid=False, showticklabels=False)
    fig.update_yaxes(title_text='Probability score', range = (0,1.01))
    fig.update_layout(title_text='Waterfall distribution' + (f': {batch_name} ({waterfallDf.shape[0]} samples)' if batch_name is not None else ''),
                    width=figsize[0],
                    height=figsize[1],
                    autosize=False,
                    template="plotly_white")
    fig.update_layout(legend=dict(title='Highest subtype call'))
    if return_plot:
        return fig
    else:
        fig.show()


    """
    The following functions are utility functions used in this script.
    """

def convert_symbols_to_ensembl(symb_list, path=False):
    """
    Converts gene symbols to Ensembl IDs for analysis, as TALLSorts required Ensembl IDs in its counts matrix.
    Implements an iterative approach to ensure as many symbols are converted correctly to Ensembl IDs as possible, partially dealing with duplicate symbol entries.

    ...

    Parameters
    __________
    symb_list : tuple or list
        List of gene symbols

    Returns
    __________
    Dictionary of:
        'confirmed': a dictionary with keys of gene symbol and values of EnsemblId
        'unconfirmed': a list of gene symbols unable to be converted to EnsemblIds

    Outputs
    __________
    String with number of confirmed and unconfirmed symbol-ID conversions.
    """

    # generate a pyensembl genome object
    from pyensembl import EnsemblRelease
    ensembl_data = EnsemblRelease(110)

    confirmed = {}
    unconfirmed = []
    nonexistent = []
    for i in symb_list:
        try:
            z = ensembl_data.genes_by_name(i.upper())
            if len(z) == 1:
                confirmed[i] = z[0].gene_id
            else:
                unconfirmed.append(i)
        except:
            nonexistent.append(i)
            continue
    
    # process of elimination
    fixed = 1
    message(f'Unconfirmed: {len(unconfirmed)}')
    while fixed > 0:
        fixed = 0
        unconfirmed2 = []
        for i in unconfirmed:
            z = ensembl_data.genes_by_name(i.upper())
            y = [i for i in z if i not in confirmed.values()]
            if len(y) == 1:
                confirmed[i] = y[0]
                fixed += 1
            else:
                unconfirmed2.append(i)
        unconfirmed = unconfirmed2.copy()
    unconfirmed += nonexistent
                
    message(f'Ensembl IDs found for {len(confirmed)} out of {len(symb_list)} genes.')
    return {'confirmed':confirmed, 'unconfirmed':unconfirmed}

def get_children_of_label(subtypeObjects, label_name):
    # A label name of the form "Level_num_parent"
    label_name_components = label_name.split('_')
    level_num = int(label_name_components[1])
    parent_label = '_'.join(label_name_components[2:])

    if level_num == 1:
        return sorted([i for i in subtypeObjects if subtypeObjects[i].level == 1])
    parent_obj = subtypeObjects[parent_label]
    return [i.label for i in parent_obj.children]

def clean_label(label):
    label = str(label)
    label = label.replace('/', '_')
    return label

def get_colours_for_labels(label_list, use_default=True):
    """
    Generates a dict of labels with their associated colours to show in waterfall figures

    Parameters
    __________
    label_list: list of labels
    use_default: bool
        Whether or not to use the default_label_colours for labels defined by the default tallsorts model

    Returns
    __________
    Dict containing label:rgb key pairs
    """

    default_label_colours = {
        'BCL11B':'#222222',
        'HOXA_KMT2A':'#F9DA49',
        'HOXA_MLLT10':'#91D44B',
        'NKX2':'#8E3CCE', 
        'TAL/LMO':'#DF3524',
        'TLX1':'#367BD8',
        'TLX3':'#57BFE0',
        'Diverse':'#ED75B2',
        'Unclassified':'#808080',
        'TAL2':'#E88E8E',
    }
    label_colours = {}
    unaccounted_labels = []
    if use_default:
        for i in label_list:
            if i in default_label_colours:
                label_colours[i] = default_label_colours[i]
            else:
                unaccounted_labels.append(i)
    else:
        unaccounted_labels = [i for i in label_list]

    if unaccounted_labels:
        import colorsys
        def rgb_to_hex(rgb):
            hex_code = '#'
            hex_raw = [hex(int(i*255))[2:].upper() for i in rgb]
            for i in hex_raw:
                hex_code += '0'+i if len(i)<2 else i
            return hex_code
        
        unaccounted_hues = [rgb_to_hex(colorsys.hsv_to_rgb(i,1,1)) for i in np.linspace(0,1,len(unaccounted_labels)+1)]
        for i in range(len(unaccounted_labels)):
            label_colours[unaccounted_labels[i]] = unaccounted_hues[i]
        
    return label_colours

    

"""
The following are functions used in fitting a model
"""
def fit_classifier(ui, n_jobs=1):
    X = ui.samples
    sample_sheet = ui.sample_sheet
    hierarchy = ui.hierarchy
    training_params = ui.training_params
    destination = ui.destination

    message("Checking validity of input files.")
    check_hierarchy(hierarchy)
    subtypeObjects = genSubtypeObjsFromHierarchy(hierarchy)
    check_training_inputs(X, sample_sheet, subtypeObjects)
    logreg_params = gen_logreg_params(training_params, subtypeObjects)
    scalers = {}
    clfs = {}

    message("Training classifier. This could take some time...")

    ### creating the scalers
    ###

    def create_scalers(X, parent_label, filter=True):
        if parent_label == 'Level0':
            children_labels = [i for i in subtypeObjects if subtypeObjects[i].level == 1]
        else:
            subset_samples = sample_sheet.index[sample_sheet[parent_label] == 1]
            X = X.loc[subset_samples]
            children_labels = [i.label for i in subtypeObjects[parent_label].children]

        if filter:
            min_subtype = min([sum(sample_sheet.loc[X.index][label] == 1) for label in children_labels])
            X = X[filter_genes(X, min_subtype)]
        scalers[parent_label] = createScaler(X)
    
    parent_labels = ['Level0'] + sorted([i for i in subtypeObjects if subtypeObjects[i].children], key=lambda x:subtypeObjects[x].level)
    with parallel_backend('threading', n_jobs=n_jobs):
        Parallel(verbose=0)(delayed(create_scalers)(X, parent_label, filter=ui.filter) for parent_label in parent_labels)

    ### performing model training
    ###

    def performing_training(X, label, logreg_params):
        # training model (note this is specific to label)
        parent_label = subtypeObjects[label].parent.label if subtypeObjects[label].parent else 'Level0'
        if parent_label != 'Level0':
            subset_samples = sample_sheet.index[sample_sheet[parent_label] == 1]
            X_subset = X.loc[subset_samples]
        else:
            X_subset = X.copy()
        scaler = scalers[parent_label]
        X_train = scaleForTesting(X_subset, scaler)
        y_train = sample_sheet.loc[X_train.index][label] == 1
        # logreg_params: random_state=0, max_iter=10000, tol=0.0001, penalty='l1', solver='saga', C=0.2, class_weight='balanced'
        logreg = LogisticRegression(**logreg_params)
        clf = logreg.fit(X_train, y_train)
        subtypeObjects[label].clf = clf
        message(f'Trained label {label}')

    with parallel_backend('threading', n_jobs=n_jobs):
        Parallel(verbose=1)(delayed(performing_training)(X, label, logreg_params[label]) for label in subtypeObjects)

    ### completing training and saving model
    ###

    custom_model = {
        'hierarchy':gen_hierarchy_dict(subtypeObjects),
        'scalers':scalers,
        'clfs':{i:subtypeObjects[i].clf for i in subtypeObjects},
        'is_default':False
    }

    steps = [('clf', Classifier(tallsorts_model_dict=custom_model))]
    tallsorts = TALLSorts(steps)

    with gzip.open(f'{destination}/custom.pkl.gz', 'wb') as f:
        pickle.dump(tallsorts, f)

    message("Finished. You can find the custom model in the directory you sepcified.")
    sys.exit()

def check_hierarchy(hierarchy):
    if 'Parent' not in hierarchy.columns:
        message(f"Error: Hierarchy file does not contain 'Parent' as a column title. Exiting.")
        sys.exit()

    duplicate_labels = hierarchy.index.value_counts()[hierarchy.index.value_counts() > 1]
    if duplicate_labels.shape[0] > 0:
        message(f"Error: Label '{duplicate_labels.index[0]}' appears at least twice in the first column of the hierarchy file. Exiting.")
        sys.exit()

    for i in hierarchy['Parent']:
        if i and i not in hierarchy.index:
            message(f"Error: {i} is listed as a parent label, but does not exist as its own label. Exiting.")
            sys.exit()


def check_training_inputs(X, sample_sheet, subtypeObjects):
    """
    Various checks to make sure that X, sample_sheet, and subtypeObjects are mutually compatible, specifically ensuring samples and labels all match up.
    """
    # check all samples in X are listed in the sample_sheet
    for i in X.index:
        if i not in sample_sheet.index:
            message(f"Error: Sample '{i}' is in the counts matrix but not in the sample sheet. Exiting.")
            sys.exit()

    # check all sample_sheet labels are unique
    duplicate_labels =  sample_sheet.columns.value_counts()[sample_sheet.columns.value_counts() > 1]
    if duplicate_labels.shape[0] > 0:
        message(f"Error: Label '{duplicate_labels.index[0]}' appears at least twice in the headers of the sample-sheet file. Exiting.")
        sys.exit()
    
    # check all sample_sheet labels are within the hierarchy
    for i in sample_sheet.columns:
        if i not in subtypeObjects:
            message(f"Error: Subtype label '{i}' is in the sample sheet but not in the hierarchy. Exiting.")
            sys.exit()

    # check that every sample, if will be sent to further classifier, has positives for all parents
    max_levels = max([subtypeObjects[i].level for i in subtypeObjects])
    for sample in sample_sheet.index:
        true_classifications = sample_sheet.loc[sample]
        positive_labels =  true_classifications[true_classifications > 0.5].index
        for label in positive_labels:
            cur_label = label
            for level in range(max_levels):
                if subtypeObjects[cur_label].parent is None:
                    break
                if subtypeObjects[cur_label].parent.label not in positive_labels:
                    message(f"Error: Sample '{sample}' is positive for '{cur_label}' but negative for its parent '{subtypeObjects[cur_label].parent.label}'. Exiting.")
                    sys.exit()
                cur_label = subtypeObjects[cur_label].parent.label

def gen_logreg_params(training_params, subtypeObjects):
    default_params = dict(random_state=0, max_iter=10000, tol=0.0001, penalty='l1', solver='saga', C=0.2, class_weight='balanced')
    param_modifiers = dict(random_state=int, max_iter=int, tol=float, penalty=str, solver=str, C=float, class_weight=str)
    logreg_params = {}
    if training_params is None:
        logreg_params = {i:default_params.copy() for i in subtypeObjects}
        return logreg_params

    for label in subtypeObjects:
        logreg_params[label] = default_params.copy()
        if label in training_params.index:
            row = training_params.loc[label]
            for property in row.index:
                if row[property]:
                    logreg_params[label][property] = param_modifiers[property](row[property])
    
    return logreg_params

def filter_genes(X, min_subtype, verbose=False):
    from pyensembl import EnsemblRelease
    ensembl_data = EnsemblRelease(110)
    
    candidate_genes = X.columns
    if verbose:
        message(f'There are {len(candidate_genes)} genes initially.')

    ### Removing genes not in the annotation set
    not_found = []
    for i in candidate_genes:
        try:
            ensembl_data.gene_by_id(i)
        except:
            not_found.append(i)
    candidate_genes = [i for i in candidate_genes if i not in not_found]
    if verbose:
        message(f'Removed genes not in the annotation set. There are now {len(candidate_genes)} genes.')

    ### Removing Y-chromosome genes and XIST
    Y = ensembl_data.gene_ids(contig='Y') + [ensembl_data.genes_by_name('XIST')[0].gene_id]
    candidate_genes = [i for i in candidate_genes if i not in Y]
    if verbose:
        message(f'Removed Y-chromosome and XIST genes. There are now {len(candidate_genes)} genes.')
    
    ### Removing noncoding genes and pseudogenes
    categories_to_keep = ['protein_coding']
    candidate_genes = [i for i in candidate_genes if ensembl_data.gene_by_id(i).biotype in categories_to_keep]
    if verbose:
        message(f'Removed There are {len(candidate_genes)} coding genes remaining.')

    ### Removing mitochondrial genes
    MT = [i for i in candidate_genes if ensembl_data.gene_by_id(i).contig == 'MT']
    candidate_genes = [i for i in candidate_genes if i not in MT]
    if verbose:
        message(f'Removed mitochondrial genes. There are now {len(candidate_genes)} genes.')
    
    ### Converting to CPM
    X_cpm = conorm.cpm(X.transpose()).transpose()
    
    ### Remove all genes that have fewer than 5 counts in fewer samples than the smallest subtype
    cpm_threshold = 5/min(X.sum(axis=1)) * 1e6
    to_remain = X.columns[(X_cpm >= cpm_threshold).sum(axis=0) >= min_subtype]
    candidate_genes = [i for i in candidate_genes if i in to_remain]
    if verbose:
        message(f'Candidate genes remaining: {len(candidate_genes)}')
    
    ### sorting
    candidate_genes.sort()

    return candidate_genes
