import argparse
import os
import yaml
import torch
import pandas as pd
import flexynesis
import warnings

def main():
    parser = argparse.ArgumentParser(description="Flexynesis - Your PyTorch model training interface")
    
    parser.add_argument("--data_path", help="Path to the folder with train/test data files", type=str)
    parser.add_argument("--model_class", help="The kind of model class to instantiate", type=str, choices=["DirectPred", "supervised_vae", "MultiTripletNetwork"])
    parser.add_argument("--target_variables", help="Which variables in 'clin.csv' to use for predictions, comma-separated if multiple", type = str)
    parser.add_argument("--batch_variables", help="(Optional) Which variables in 'clin.csv' to use for data integration / batch correction, comma-separated if multiple", type = str)
    parser.add_argument("--fusion_type", help="How to fuse the omics layers", type=str, choices=["early", "intermediate"])
    parser.add_argument("--hpo_iter", help="Number of iterations for hyperparameter optimisation", type=int)
    parser.add_argument("--features_min", help="Minimum number of features to retain after feature selection", type=int)
    parser.add_argument("--features_top_percentile", help="Top percentile features to retain after feature selection", type=float)
    parser.add_argument("--data_types", help="Which omic data matrices to work on, comma-separated: e.g. 'gex,cnv'", type=str)
    parser.add_argument("--outdir", help="Path to the output file to save the model outputs", type=str)
    parser.add_argument("--prefix", help="Job prefix to use for output files", type=str)
    
    torch.set_num_threads(4)
    warnings.filterwarnings("ignore", ".*does not have many workers.*")
    warnings.filterwarnings("ignore", "has been removed as a dependency of the")
    warnings.filterwarnings("ignore", "The `srun` command is available on your system but is not used")

    args = parser.parse_args()

    # Validate the data path
    if not os.path.isdir(args.data_path):
        raise ValueError(f"Invalid data_path: {args.data_path}")

    if args.model_class == "DirectPred":
        model_class = flexynesis.DirectPred
        config_name = 'DirectPred'
    elif args.model_class == "supervised_vae":
        model_class = flexynesis.supervised_vae
        config_name = 'SVAE'
    elif args.model_class == "MultiTripletNetwork":
        model_class = flexynesis.MultiTripletNetwork
        config_name = 'MultiTripletNetwork'
    else:
        raise ValueError(f"Invalid model_class: {args.model_class}")

    # import assays and labels
    inputDir = args.data_path
    
    # Set concatenate to True to use early fusion, otherwise it will run intermediate fusion
    concatenate = False 
    if args.fusion_type == 'early':
        concatenate = True
        
    data_importer = flexynesis.DataImporter(path = args.data_path, 
                                            data_types = args.data_types.strip().split(','),
                                            concatenate = concatenate, 
                                            min_features= args.features_min, 
                                            top_percentile= args.features_top_percentile)
    
    train_dataset, test_dataset = data_importer.import_data()
    
    # define a tuner object, which will instantiate a DirectPred class 
    # using the input dataset and the tuning configuration from the config.py
    tuner = flexynesis.HyperparameterTuning(train_dataset, 
                                            model_class = model_class, 
                                            target_variables = args.target_variables,
                                            batch_variables = args.batch_variables,
                                            config_name = config_name, 
                                            n_iter=int(args.hpo_iter))    
    
    # do a hyperparameter search training multiple models and get the best_configuration 
    model, best_params = tuner.perform_tuning()
    
    # make predictions on the test dataset
    y_pred_dict = model.predict(test_dataset)
    
    # evaluate predictions 
    # Create an empty list to store metrics
    metrics_list = []

    # Evaluate predictions
    print("Computing model evaluation metrics")
    for var in y_pred_dict.keys():
        ind = ~torch.isnan(test_dataset.ann[var])
        if test_dataset.variable_types[var] == 'numerical':
            metrics = flexynesis.evaluate_regressor(test_dataset.ann[var][ind], y_pred_dict[var][ind])
        else:
            metrics = flexynesis.evaluate_classifier(test_dataset.ann[var][ind], y_pred_dict[var][ind])

        for metric, value in metrics.items():
            metrics_list.append({
                'var': var,
                'variable_type': test_dataset.variable_types[var],
                'metric': metric,
                'value': value
            })

    # Convert the list of metrics to a DataFrame
    metrics_df = pd.DataFrame(metrics_list)
    metrics_df.to_csv(os.path.join(args.outdir, '.'.join([args.prefix, 'stats.csv'])), header=True, index=False)
    
    # compute feature importance values
    print("Computing variable importance scores")
    df_list = []
    for var in model.variables:
        df_list.append(model.compute_feature_importance(var, steps = 20))
    df_imp = pd.concat(df_list, ignore_index = True)
    df_imp.to_csv(os.path.join(args.outdir, '.'.join([args.prefix, 'feature_importance.csv'])), header=True, index=False)

    
if __name__ == "__main__":
    main()
