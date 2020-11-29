"""Results of POMATO."""

import json
import logging

import matplotlib.pyplot as plt
# import sys
import numpy as np
import pandas as pd

import pomato.tools as tools
# pylint: disable-msg=E1101

class Results():
    """Results of POMATO makes market results available to the user.

    The Results module provides an interface between the market result
    and the data itself. All result variables are set as an attribute in a long
    DataFrame with its sets as columns which can be easily accessed
    with *result.VAR*.

    Attributes
    ----------
    data : :class:`~pomato.data.DataManagement`
        An instance of the DataManagement class with the processed input data
        that is the basis of the loaded results.
    grid : :class:`~pomato.grid.GridTopology`
        An instance of the GridTopology class, to provide its functionality to the results.
    result_folder : pathlib.Path
        The data is initialized from a folder containing the result. The Results
        can be initialized after a model run or from stored data.
    result_attributes : dict,
        *result_attributes* covers all variables from the market model,
        along with dual and infeasibility/slack variables and other market
        model specific information which are relevant to the results itself.

    Parameters
    ----------
    data : :class:`~pomato.data.DataManagement`
        An instance of the DataManagement class with the processed input data
        that is the basis of the loaded results.
    grid : :class:`~pomato.grid.GridTopology`,
        An instance of the GridTopology class, to provide its functionality to the
        results.
    result_folder : pathlib.Path
        Folder with the results of the market model in .csv files.
    """

    def __init__(self, data, grid, result_folder):
        self.logger = logging.getLogger('Log.MarketModel.DataManagement.ResultData')
        self.data = data
        self.grid = grid

        result_folder_name = str(result_folder).split("\\")[-1]

        self.output_folder = self.data.wdir.joinpath("data_output").joinpath(result_folder_name)

        variables = {variable: False for variable in ["G", "H",
                                                      "D_es", "L_es",
                                                      "D_hs", "L_hs",
                                                      "INJ", "EX",
                                                      "D_ph", "F_DC", "CURT", "Alpha"]}

        dual_variables = {variable: False for variable in ["EB_nodal", "EB_zonal", "EB_heat"]}

        infeasibility_variables = {variable: False
                                   for variable in ["INFEAS_H_POS", "INFEAS_H_NEG",
                                                    "INFEAS_EL_N_POS", "INFEAS_EL_N_NEG",
                                                    "INFEAS_LINES"]}

        self.result_attributes = {"variables": variables,
                                  "dual_variables": dual_variables,
                                  "infeasibility_variables": infeasibility_variables,
                                  "model_horizon": None, "source": None, "status": None,
                                  "objective": None, "t_start": None, "t_end": None,
                                  "is_redispatch_result": False, 
                                  "corresponding_market_result_name": None}

        self.model_horizon = self.result_attributes["model_horizon"]

        for var in self.result_attributes["variables"]:
            setattr(self, var, pd.DataFrame())
        for var in self.result_attributes["dual_variables"]:
            setattr(self, var, pd.DataFrame())
        for var in self.result_attributes["infeasibility_variables"]:
            setattr(self, var, pd.DataFrame())

        # Add opt Set-Up to the results attributes
        self.result_attributes["source"] = result_folder
        self.result_attributes["name"] = str(result_folder).split("\\")[-1]
        self.load_results_from_folder(result_folder)

        # Set Redispatch = True if result is a redispatch result 
        if "redispatch" in self.result_attributes["name"]:
            self.result_attributes["is_redispatch_result"] = True
            market_result_name = "_".join(self.result_attributes["name"].split("_")[:3]) + "_market_results"
            if market_result_name in self.data.results:
                self.result_attributes["corresponding_market_result_name"] = "_".join(self.result_attributes["name"].split("_")[:3]) + "_market_results"
            else:
                self.logger.warning("Corresponding market results to %s not or with new name instantiated", self.result_attributes["name"])
                self.logger.warning("Manually set market result name in result attributes.")
        # set-up: don't show the graphs when created
        plt.ioff()

    def load_results_from_folder(self, folder):
        """Load results from folder.

        Results are loaded as csv files from results folder with additional
        information inform of the options file that was used to get the results
        as well as the model horizon which is extracted from the INJ variable.

        All variables are set as an attribute of this instance of
        ResultProcessing.

        Parameters
        ----------
        folder : pathlib.Path
            Folder with the results of the market model.
        """
        folder_name = str(folder).split("\\")[-1]
        self.logger.info("Loading Results from results folder %s", folder_name)

        for variable_type in ["variables", "dual_variables", "infeasibility_variables"]:
            for var in self.result_attributes[variable_type]:
                try:
                    setattr(self, var, pd.read_csv(str(folder.joinpath(f"{var}.csv"))))
                    self.result_attributes[variable_type][var] = True
                except FileNotFoundError:
                    self.logger.warning("%s not in results folder %s", var, folder_name)

        # Set result attributes from result json file or data.option:
        try:
            with open(str(folder.joinpath("misc_results.json")), "r") as jsonfile:
                self.result_attributes["objective"] = json.load(jsonfile)
        except FileNotFoundError:
            self.logger.warning("Results Not Found. This is an Error")
            
        try:
            with open(str(folder.joinpath("optionfile.json")), "r") as jsonfile:
                self.result_attributes = {**self.result_attributes,
                                          **json.load(jsonfile)}
        except FileNotFoundError:
            self.logger.warning("No options file found in result folder, \
                                using data.options")
            self.result_attributes = {**self.result_attributes,
                                      **self.data.options["optimization"]}

        # Model Horizon as attribute
        self.result_attributes["model_horizon"] = list(self.INJ.t.unique())
        self.model_horizon = self.result_attributes["model_horizon"]



    def redispatch(self):
        """Return Redispatch"""

        # Find corresponding Market Result
        tmp = [result for result in self.data.results if "market" in result]
        if len(tmp) == 1:
            market_result = self.data.results[tmp[0]]
        else:
            raise AttributeError("Multiple/None market-results available for redispatch")

        gen = pd.merge(market_result.data.plants[["plant_type", "g_max", "node"]],
                       market_result.G, left_index=True, right_on="p")

        # Redispatch Calculation G_redispatch - G_market
        gen = pd.merge(gen, self.G, on=["p", "t"], suffixes=("_market", "_redispatch"))
        gen["delta"] = gen["G_redispatch"] - gen["G_market"]
        gen["delta_abs"] = gen["delta"].abs()

        # Redispatch Values
        self.logger.info("Redispatch Values per timestep: sum: %d, abs sum: %d", round(gen.delta.sum()/len(gen.t.unique())), 
                         round(gen.delta_abs.sum()/len(gen.t.unique())))
        return gen


    def infeasibility(self):
        """Return electricity infeasibilities"""
        infeas = pd.merge(self.data.nodes, self.INFEAS_EL_N_POS, left_index=True, right_on="n")
        infeas = pd.merge(infeas, self.INFEAS_EL_N_NEG, on=["t", "n"])
        infeas = infeas.rename(columns={"INFEAS_EL_N_POS": "pos", "INFEAS_EL_N_NEG": "neg"})
        return infeas[(infeas.pos > 0) | (infeas.neg > 0)]

    def price(self):
        """Return electricity prices.

        Returns the dual of the energy balances (nodal and zonal). Since
        the model can be cleared with constraints on both simultaneously, the
        resulting nodal price is the sum of the zonal and nodal components.
        The dual is obtained from Julia/JuMP with the dual function and therefore
        multiplied with -1.

        Returns
        -------
        price : DataFrame
            Price DataFrame with columns timestep (t), node (n), zone (z) and
            price (marginal).
        """
        eb_nodal = self.EB_nodal.copy()
        eb_nodal = pd.merge(eb_nodal, self.data.nodes.zone.to_frame(),
                            how="left", left_on="n", right_index=True)
        eb_nodal.loc[abs(eb_nodal.EB_nodal) < 1E-3, "EB_nodal"] = 0

        eb_zonal = self.EB_zonal.copy()
        eb_zonal.loc[abs(eb_zonal.EB_zonal) < 1E-3, "EB_zonal"] = 0

        price = pd.merge(eb_nodal, eb_zonal, how="left",
                         left_on=["t", "zone"], right_on=["t", "z"])

        price["marginal"] = -(price.EB_zonal + price.EB_nodal)
        return price[["t", "n", "z", "marginal"]]

    def commercial_exchange(self, from_zone, to_zone):
        """Return commercial exchange for a pair of market areas.

        Parameters
        ----------
        from_zone : str
           Exporting market area.
        to_zone : str
           Importing market area.

        Returns
        -------
        exchange : DataFrame
            Commercial exchange between two market areas. 
        """

        from_to = self.EX[(self.EX.z == from_zone)&(self.EX.zz == to_zone)]
        to_from = self.EX[(self.EX.z == to_zone)&(self.EX.zz == from_zone)]

        from_to = from_to.loc[:, ["t", "z", "zz", "EX"]].set_index("t")
        to_from = to_from.loc[:, ["t", "z", "zz", "EX"]].set_index("t")

        exchange = pd.merge(from_to, to_from, left_index=True, right_index=True)

        exchange = exchange.loc[:, ["EX_x", "EX_y"]]
        exchange.columns = ["-".join([from_zone, to_zone]), "-".join([to_zone, from_zone])]
        exchange.loc[:, "-".join([to_zone, from_zone])] *= -1

        return exchange

    def net_position(self):
        """Calculate net position for each zone and timestep.

        Returns
        -------
        net_position : DataFrame
            DataFrame with the timesteps as index and zones as columns.
        """
        net_position = pd.DataFrame(index=self.EX.t.unique())
        for zone in self.data.zones.index:
            net_position[zone] = self.EX[self.EX.z == zone].groupby("t").sum() - \
                                 self.EX[self.EX.zz == zone].groupby("t").sum()
        return net_position

    def check_infeasibilities(self):
        """Check for infeasibility variables.

        Checks for infeasibility variables in electricity/heat energy balance
        and line infeasibility variables. These are added to avoid infeasibility
        of the model and adding slack to constraints at predefined costs.
        Logs warning, returns nothing.
        """
        numerics = ['int16', 'int32', 'int64', 'float16', 'float32', 'float64']
        for infeasibilities in self.result_attributes["infeasibility_variables"]:
            tmp = getattr(self, infeasibilities)
            for col in tmp.select_dtypes(include=numerics):
                if any(tmp[col] > 1e-3):
                    self.logger.warning("Infeasibilities in %s", col)

    def check_curtailment(self):
        """[Deprecated] Check for curtailment of plants of type ts (i.e. with availabilities).

        Deprecated: changed curtailment to explicit variable.
        Curtailment is checked by comparing actual with potential generation.

        Returns
        -------
        gen : DataFrame
            DataFrame with actual and potential generation for each plant and
            timestep.
        """
        
        ts_option = self.data.options["optimization"]["plant_types"]["ts"]
        res_plants = self.data.plants[self.data.plants.plant_type.isin(ts_option)].copy()

        gen = self.G.copy()
        ava = self.data.availability[["timestep", "plant", "availability"]].copy()
        ava.columns = ["t", "p", "ava"]

        gen = gen[gen.p.isin(res_plants.index)]
        gen = pd.merge(gen, res_plants[["g_max"]], how="left", left_on="p", right_index=True)
        gen = pd.merge(gen, ava, how="left", on=["p", "t"])

        gen.ava.fillna(1, inplace=True)

        gen["ava_gen"] = gen.g_max*gen.ava
        gen["curt"] = gen.ava_gen - gen.G
        curtailment = gen["curt"].round(3).sum()
        self.logger.info("%s MWh curtailed in market model results!", curtailment)
        return gen

    def res_share(self, res_plant_type):
        """Calculate the share of renewables.
        
        Returns
        -------
        res_share : float
            Share of reneable generation in the resulting dispatch.
        """
        
        res_plants = self.data.plants[self.data.plants.plant_type.isin(res_plant_type)]
        
        gen = self.G
        gen_res = gen[gen.p.isin(res_plants.index)]
        res_share = gen_res.G.sum()/gen.G.sum()
        self.logger.info("Renewable share is %d %% in resulting dispatch!",
                         round(res_share*100, 2))
        return res_share

    def default_plots(self, show_plot=False):
        """Set of Standard Plots that can be helpful.

        This is just a bunch of random plots that where helpful to me at some
        point.

        Plots are saved onto *data_output/self.output_folder*, which is created
        if it does not exist.

        Parameters
        ----------
        show_plot : bool, optional
            Whether or not plot should be shown immediately.
        """
        if show_plot:
            plt.ion()
        if not self.output_folder.is_dir():
            self.output_folder.mkdir()

        plant_columns = [col for col in ["node", "fuel", "tech", "plant_type"] if col in self.data.plants.columns]

        generation = pd.merge(self.G, self.data.plants[plant_columns],                      
                            how="left", left_on="p", right_index=True)

        generation = pd.merge(generation, self.data.nodes.zone.to_frame(),
                            how="left", left_on="node", right_index=True)
        model_horizon = self.result_attributes["model_horizon"]

        fig, ax = plt.subplots()
        group_by = "plant_type"
        gen_plot = generation.groupby(["t", group_by], as_index=False).sum()
        gen_plot.pivot(index="t", columns=group_by,
                        values="G").plot.area(ax=ax,
                                            xticks=[x for x in range(0, len(model_horizon))],
                                            figsize=(20, 10), rot=45)
        ax.legend(loc='upper right')
        ax.margins(x=0)
        fig.savefig(str(self.output_folder.joinpath("gen_type.png")))

        # Aggregated example
        fig, ax = plt.subplots()
        gen_plot.groupby(group_by).sum().plot.pie(ax=ax, y="G", figsize=(20, 20),)
        ax.legend(loc='upper right')
        ax.margins(x=0)
        fig.savefig(str(self.output_folder.joinpath("gen_fuel_pichart.png")))

        # Renewables generation
        fig, ax = plt.subplots()
        res_type = self.data.options["optimization"]["plant_types"]["ts"]

        res_gen = (generation[generation.plant_type.isin(res_type)]
                .groupby(["t", "fuel"], as_index=False).sum())
        if not res_gen.empty:
            res_gen.pivot(index="t", columns="fuel",
                        values="G").plot(ax=ax, xticks=[x for x in range(0, len(model_horizon))],
                                        figsize=(20, 10), rot=45)
            ax.legend(loc='upper right')
            ax.margins(x=0)
            fig.savefig(str(self.output_folder.joinpath("gen_res.png")))

        # Storage Generation, Demand and LEvel
        fig, ax = plt.subplots()
        stor_d = self.D_es.groupby(["t"], as_index=True).sum()
        stor_l = self.L_es.groupby(["t"], as_index=True).sum()
        stor_type = self.data.options["optimization"]["plant_types"]["ts"]
        stor_g = generation[generation.plant_type.isin(stor_type)].groupby(["t"], as_index=True).sum()
        if not all([data.empty for data in [stor_d, stor_l, stor_g]]):
            (pd.concat([stor_d, stor_l, stor_g], axis=1)
            .plot(ax=ax, xticks=[x for x in range(0, len(model_horizon))],
                figsize=(20, 10), rot=45))
            ax.legend(loc='upper right')
            ax.margins(x=0)
            fig.savefig(str(self.output_folder.joinpath("storage.png")))

        # Close all Figures
        fig.clf()

    # Grid Analytics - Load Flows
    def n_0_flow(self, timesteps=None):
        """Calculate N-0 Flows.

        Calculates the N-0 power flows on all lines. Optionally just calculate
        for a list/subset of timesteps.

        Parameters
        ----------
        timesteps : list like, optional
            Set of timesteps to calculate the power flow for. Defaults to the
            full model horizon.

        Returns
        -------
        n_0_flows : DataFrame
            N-0 power flows for each line.
        """
        if not timesteps:
            self.logger.info("Calculating N-0 Flows for the full model horizon")
            timesteps = self.result_attributes["model_horizon"]

        # n_0_flows = pd.DataFrame(index=self.data.lines.index)
        # for t in timesteps:
        #     n_0_flows[t] = np.dot(self.grid.ptdf, self.INJ.INJ[self.INJ.t == t].values)

        inj = self.INJ.pivot(index="t", columns="n", values="INJ")
        inj = inj.loc[timesteps, self.data.nodes.index]
        flow = np.dot(self.grid.ptdf, inj.T)
        n_0_flows = pd.DataFrame(index=self.data.lines.index, columns=timesteps, data=flow)

        return n_0_flows

    def n_1_flow(self, timesteps=None, lines=None, outages=None, sensitivity=5e-2):
        """N-1 power flows on lines (cb) under outages (co).

        Calculates the power flows on the specified lines under the specified
        outages for the specified timesteps.

        All arguments are optional and per default this method calculates the
        power flow on all lines considering outages with significant impact.
        This is calculated with :meth:`~pomato.grid.create_filtered_n_1_ptdf`
        where this is described in greater detail.

        Parameters
        ----------
        timesteps : list like, optional
            Set of timesteps to calculate the power flow for. Defaults to the
            full model horizon.
        lines : list like, optional
            Considered lines, defaults to all.
        outages : list like, optional
            Considered lines, defaults those with > 5% sensitivity.
        sensitivity : float, optional
            The sensitivity defines the threshold from which outages are
            considered critical. An outage that can impact the line flow,
            relative to its maximum capacity, more than the sensitivity is
            considered critical. Defaults to 5%.

        Returns
        -------
        n_1_flows : DataFrame
            Returns Dataframe of N-1 power flows with lines and contingencies
            specified.
        """
        if not self.grid:
            self.logger.error("Grid not available in results object!")
            return None

        if (lines and not all([l in self.data.lines.index for l in lines])) or \
                (outages and not all([o in self.data.lines.index for o in outages])):

            self.logger.error("Not all CBs/COs are indices of lines!")
            return None

        if not timesteps:
            self.logger.info("Calculating N-1 Flows for the full model horizon")
            timesteps = self.result_attributes["model_horizon"]

        if not lines:
            self.logger.info("Using all lines from grid model as CBs")
            lines = list(self.grid.lines.index)

        use_lodf = False
        if not outages:
            self.logger.info("Using COs with a sensitivity of %d percent to CBs",
                             round(sensitivity*100, 2))
            use_lodf = True

        ptdf = [self.grid.ptdf]
        label_lines = list(self.grid.lines.index)
        label_outages = ["basecase" for i in range(0, len(self.grid.lines.index))]

        for line in self.grid.lines.index[self.grid.lines.contingency]:
            if use_lodf:
                outages = list(self.grid.lodf_filter(line, sensitivity))
            label_lines.extend([line for i in range(0, len(outages))])
            label_outages.extend(outages)

        # estimate size of array = nr_elements * bytes per element
        # (float64 + sep = 8 + 1) / (1024**2) MB
        estimate_size = len(label_lines)*len(self.grid.nodes.index)*(8 + 1)/(1024*1024)
        if estimate_size > 10000:
            self.logger.error("Estimated size of N-1 PTDF = %d", estimate_size)
            raise Exception('Matrix N-1 PTDF MAtrix too large! Use a higher sensitivity!')

        for line in self.grid.lines.index[self.grid.lines.contingency]:
            if use_lodf:
                outages = list(self.grid.lodf_filter(line, sensitivity))
            tmp_ptdf = np.vstack([self.grid.create_n_1_ptdf_cbco(line, out) for out in outages])
            ptdf.append(tmp_ptdf)

        ptdf = np.concatenate(ptdf).reshape(len(label_lines),
                                            len(list(self.grid.nodes.index)))

        inj = self.INJ.pivot(index="t", columns="n", values="INJ")
        inj = inj.loc[timesteps, self.data.nodes.index]
        flow = np.dot(ptdf, inj.T)
        n_1_flows = pd.DataFrame(columns=timesteps, data=flow)
        n_1_flows["cb"] = label_lines
        n_1_flows["co"] = label_outages

        self.logger.info("Done Calculating N-1 Flows")

        return n_1_flows.loc[:, ["cb", "co"] + timesteps]

    def absolute_max_n_1_flow(self, timesteps=None):
        """Calculate the absolute max of N-1 Flows.

        This method essentially proviedes a n_1_flow.groupby("cb") yielding the 
        absolute maximum flow, maintaining the directionality of the flow.
        Thanks @https://stackoverflow.com/a/64559655
        
        Parameters
        ----------
        timesteps : list like, optional
            Subset of model horizon. Defaults to the full model horizon.

        """

        n_1_flows = self.n_1_flow(timesteps=timesteps)
        n_1_flows = n_1_flows.drop("co", axis=1)
        n_1_flow_max = n_1_flows.groupby("cb").max()
        n_1_flow_min = n_1_flows.groupby("cb").min()
        n_1_flows = pd.DataFrame(np.where(n_1_flow_max > -n_1_flow_min, n_1_flow_max, n_1_flow_min),
                                 index=n_1_flow_min.index, columns=n_1_flow_min.columns)

        return n_1_flows.reindex(self.grid.lines.index)

    def overloaded_lines_n_0(self, timesteps=None):
        """Calculate overloaded lines (N-0) power.

        Calculates what lines are overloaded, without taking into account
        contingencies. This uses the method :meth:`~n_0_flow()` and compares
        the absolute flows to the maximum capacity.

        Parameters
        ----------
        timesteps : list like, optional
            Subset of model horizon. Defaults to the full model horizon.

        Returns
        -------
        agg_info : DataFrame
            DataFrame that provides the information which line is overloaded,
            how often an overload occurs over the specified timesteps and
            the average loading of the line. Returns an empty DataFrame when
            no line is overloaded.
        n_0_load : DataFrame
            Line loadings for the overloaded lines and considered timesteps.
        """
        if not timesteps:
            # if not specified use full model horizon
            timesteps = self.result_attributes["model_horizon"]

        flows = self.n_0_flow(timesteps)

        rel_load_array = np.vstack([(abs(flows[t]))/self.data.lines.maxflow for t in timesteps]).T
        rel_load = pd.DataFrame(index=flows.index, columns=flows.columns,
                                data=rel_load_array)

        # Only those with over loadings
        n_0_load = rel_load[np.any(rel_load.values > 1.01, axis=1)]

        agg_info = pd.DataFrame(index=n_0_load.index)
        condition = np.any(rel_load.values > 1.01, axis=1)
        agg_info["# of overloads"] = np.sum(rel_load.values > 1.01, axis=1)[condition]
        agg_info["avg load"] = n_0_load.mean(axis=1)

        return agg_info, n_0_load

    def overloaded_lines_n_1(self, timesteps=None, sensitivity=5e-2):
        """Overloaded lines under contingencies (N-1).

        Uses method :meth:`~n_1_flow()` to obtain N-1 power flows under
        contingencies. Compiles additional information for overloaded lines.
        How often are lines overloaded and under which contingencies its
        average load and whether or not an overload already occurs in the
        base case, meaning the N-0 loading.

        Parameters
        ----------
        timesteps : list like, optional
            Subset of model horizon. Defaults to the full model horizon.
        sensitivity : float, optional
            The sensitivity defines the threshold from which outages are
            considered critical. Am outage that can impact the line flow,
            relative to its maximum capacity, more than the sensitivity is
            considered critical. Defaults to 5%.

        Returns
        -------
        agg_info : DataFrame
            DataFrame that provides the information which line is overloaded,
            how often an overload occurs over the specified timesteps and
            contingencies, average loading of the line. Returns an empty
            DataFrame when no line is overloaded.
        n_1_overload : DataFrame
            Line loadings for the overloaded cbco's and considered timesteps.
        """
        if not timesteps:
            # if not specified use full model horizon
            timesteps = self.result_attributes["model_horizon"]

        n_1_flow = self.n_1_flow(timesteps=timesteps, sensitivity=sensitivity)
        n_1_load = n_1_flow.copy()

        self.logger.info("Processing Flows")
        # timesteps = self.result_attributes["model_horizon"]
        maxflow_values = self.grid.lines.maxflow[n_1_load.cb].values
        n_1_load.loc[:, timesteps] = n_1_flow.loc[:, timesteps].div(maxflow_values, axis=0).abs()

        # 2% overload as tolerance
        n_1_overload = n_1_load[~(n_1_load[timesteps] <= 1.02).all(axis=1)]
        agg_info = n_1_overload[["cb", "co"]].copy()
        agg_info["# of overloads"] = np.sum(n_1_overload[timesteps] > 1, axis=1).values
        agg_info["# of COs"] = 1
        agg_info = agg_info.groupby("cb").sum()
        agg_info["avg load"] = n_1_overload.groupby(by=["cb"]).mean().mean(axis=1).values

        condition = n_1_overload.co == "basecase"
        bool_values = [line in n_1_overload.cb[condition].values for line in agg_info.index]
        agg_info["basecase overload"] = bool_values
        self.logger.info("Done")

        return agg_info, n_1_overload
